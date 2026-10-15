/**
 * 文件持久预算账本——createMemoryBudgetStore 的落盘镜像（标准：真实产品需稳定
 * 任务 ID 与持久化存储；本实现为单用户本地场景的原子写（tmp+rename）版本）。
 *
 * 语义逐条对齐 pi-agent-runtime/src/budget.ts 的内存版：同一 taskId 只认一份
 * 配置身份（configuration hash 不符 → CONFIGURATION_CHANGED）；同任务单
 * owner（TASK_BUSY）；uncapped 策略的 reserve/settle 计量与有限策略的累计墙
 * 判定一致。差异仅一处：进程启动时丢弃 owner（崩溃后的 lease 无人释放；单
 * 用户本地场景以串行队列保证无并发持有，不盲目重放未结算效果）。
 */
import {existsSync, mkdirSync, readFileSync, renameSync, writeFileSync} from "node:fs";
import {dirname} from "node:path";
import {RuntimeFault} from "pi-agent-runtime";
import type {BudgetLease, BudgetStore, Limits, UncappedBudgetLease, UncappedLimits, Usage} from "pi-agent-runtime";

interface TaskState {
  configuration: string;
  limits: Limits | UncappedLimits;
  usage: Usage & {inputTokens?: number; reservedOutputTokens?: number};
  owner?: string;
}

const uncapped = (limits: Limits | UncappedLimits): limits is UncappedLimits =>
  (limits as UncappedLimits).cumulative === "unlimited";

function counted(n: number): number {
  if (!Number.isSafeInteger(n)) throw new RuntimeFault("BUDGET_EXHAUSTED");
  return n;
}

export function createFileBudgetStore(file: string): BudgetStore {
  const tasks = new Map<string, TaskState>();
  const load = () => {
    if (!existsSync(file)) return;
    try {
      const raw = JSON.parse(readFileSync(file, "utf8")) as [string, TaskState][];
      for (const [id, t] of raw) {
        delete t.owner;  // 崩溃遗留 lease 不盲目恢复（见文件头）
        tasks.set(id, t);
      }
    } catch { /* 损坏账本按空账本处理，审计侧可见异常计量 */ }
  };
  const save = () => {
    mkdirSync(dirname(file), {recursive: true});
    const tmp = `${file}.tmp`;
    writeFileSync(tmp, JSON.stringify([...tasks]));
    renameSync(tmp, file);
  };
  load();

  async function claimAny(taskId: string, runId: string, configuration: string,
                          limits: Limits | UncappedLimits): Promise<BudgetLease | UncappedBudgetLease> {
    if (uncapped(limits)) {
      const keys = Object.keys(limits).sort().join(",");
      if (keys !== "controlTimeoutMs,maxOutputTokens,modelTimeoutMs,cumulative,toolTimeoutMs".split(",").sort().join(","))
        throw new RuntimeFault("INVALID_REQUEST");
    }
    let task = tasks.get(taskId);
    if (!task) {
      task = {configuration, limits: {...limits},
              usage: {modelCalls: 0, toolCalls: 0, outputTokens: 0, resourceUnits: 0, activeMs: 0,
                      ...(uncapped(limits) ? {inputTokens: 0, reservedOutputTokens: 0} : {})}};
      tasks.set(taskId, task);
      save();
    }
    if (task.configuration !== configuration) throw new RuntimeFault("CONFIGURATION_CHANGED");
    if (task.owner) throw new RuntimeFault("TASK_BUSY");
    if (!uncapped(task.limits) && task.usage.activeMs >= (task.limits as Limits).wallTimeMs)
      throw new RuntimeFault("BUDGET_EXHAUSTED");
    task.owner = runId;
    save();
    const state = task;
    const assertOwner = () => {if (state.owner !== runId) throw new RuntimeFault("TASK_BUSY");};
    const reserve = (maximum?: number) => {
      assertOwner();
      const free = uncapped(state.limits);
      if (maximum === undefined) {
        if (free) throw new RuntimeFault("INVALID_REQUEST");
        maximum = (state.limits as Limits).outputTokens - state.usage.outputTokens;
      }
      if (!Number.isSafeInteger(maximum) || maximum < 1)
        throw new RuntimeFault(free ? "INVALID_REQUEST" : "BUDGET_EXHAUSTED");
      const tokens = free ? maximum
        : Math.min(maximum, (state.limits as Limits).outputTokens - state.usage.outputTokens);
      if (!uncapped(state.limits) && (state.usage.modelCalls >= (state.limits as Limits).modelCalls || tokens <= 0 ||
        ((state.limits as Limits).resourceUnits !== undefined &&
         state.usage.resourceUnits + 1 > (state.limits as Limits).resourceUnits!)))
        throw new RuntimeFault("BUDGET_EXHAUSTED");
      state.usage.modelCalls = counted(state.usage.modelCalls + 1);
      state.usage.resourceUnits = counted(state.usage.resourceUnits + 1);
      state.usage.outputTokens = counted(state.usage.outputTokens + tokens);
      if (free) state.usage.reservedOutputTokens = counted(state.usage.reservedOutputTokens! + tokens);
      save();
      return tokens;
    };
    const settle = async (reserved: number, actual: number, input = 0) => {
      assertOwner();
      if (!Number.isSafeInteger(reserved) || reserved < 1 || !Number.isSafeInteger(actual) || actual < 0 ||
          (!uncapped(state.limits) && actual > reserved)) throw new RuntimeFault("BUDGET_EXHAUSTED");
      state.usage.outputTokens = counted(state.usage.outputTokens - reserved + actual);
      if (uncapped(state.limits)) {
        state.usage.inputTokens = counted(state.usage.inputTokens! + counted(input));
        state.usage.reservedOutputTokens = counted(state.usage.reservedOutputTokens! - reserved);
      }
      save();
    };
    return {
      snapshot: () => ({...state.usage}),
      async reserveModel() {return reserve();},
      async reserveModelUpTo(maximum: number) {return reserve(maximum);},
      settleModel: settle,
      async settleModelUsage(reserved: number, usage: {inputTokens: number; outputTokens: number}) {
        await settle(reserved, usage.outputTokens, usage.inputTokens);
      },
      async reserveTool(units: number) {
        assertOwner();
        counted(units);
        if (!uncapped(state.limits) && (state.usage.toolCalls >= (state.limits as Limits).toolCalls ||
          ((state.limits as Limits).resourceUnits !== undefined &&
           state.usage.resourceUnits + units > (state.limits as Limits).resourceUnits!)))
          throw new RuntimeFault("BUDGET_EXHAUSTED");
        state.usage.toolCalls = counted(state.usage.toolCalls + 1);
        state.usage.resourceUnits = counted(state.usage.resourceUnits + units);
        save();
      },
      async release(activeMs: number) {
        assertOwner();
        state.usage.activeMs = counted(state.usage.activeMs + counted(activeMs));
        delete state.owner;
        save();
      },
    };
  }
  return {
    claim: (taskId, runId, configuration, limits) => claimAny(taskId, runId, configuration, limits),
    claimUncapped: async (taskId, runId, configuration, limits) =>
      await claimAny(taskId, runId, configuration, limits) as UncappedBudgetLease,
  };
}
