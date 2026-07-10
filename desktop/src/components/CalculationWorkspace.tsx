import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import {
  Alert,
  App,
  Button,
  Flex,
  Progress,
  Segmented,
  Select,
  Skeleton,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { Ban, Gauge, Play, Square } from "lucide-react";

import { backendRequest } from "../api";
import type { ActionEvRow, ActionJob, ActionJobResponseData, Workspace } from "../types";

const PerformancePanel = lazy(() => import("./PerformancePanel"));

interface CalculationWorkspaceProps {
  workspace: Workspace;
}

function text(value: unknown): string {
  return value === null || value === undefined || value === "" ? "-" : String(value);
}

export default function CalculationWorkspace({ workspace }: CalculationWorkspaceProps) {
  const { message } = App.useApp();
  const [horizon, setHorizon] = useState<1 | 2>(1);
  const [actionMode, setActionMode] = useState<"fast" | "exact">("fast");
  const [engine, setEngine] = useState<"inventory_recursive" | "state_dp">(
    "inventory_recursive",
  );
  const [job, setJob] = useState<ActionJob | null>(null);
  const [requestError, setRequestError] = useState("");
  const capability = workspace.capabilities.action_ev;

  useEffect(() => {
    if (!job || job.status !== "running") return;
    let cancelled = false;
    const poll = async () => {
      try {
        const data = await backendRequest<ActionJobResponseData>("action_job.status", {
          game_id: workspace.game_id,
          agent_id: workspace.agent_id,
          job_id: job.job_id,
        });
        if (!cancelled) {
          setJob(data.job);
          if (data.job.status === "completed") message.success("Action EV 计算完成。 ");
        }
      } catch (caught) {
        if (!cancelled) setRequestError(caught instanceof Error ? caught.message : String(caught));
      }
    };
    const timer = window.setInterval(() => void poll(), 750);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [job, message, workspace.agent_id, workspace.game_id]);

  useEffect(() => {
    setJob(null);
    setRequestError("");
  }, [workspace.agent_id, workspace.game_id, workspace.active_target_template_id]);

  const start = async () => {
    setRequestError("");
    try {
      const data = await backendRequest<ActionJobResponseData>("action_job.start", {
        game_id: workspace.game_id,
        agent_id: workspace.agent_id,
        horizon,
        action_mode: actionMode,
        engine,
      });
      setJob(data.job);
      message.info(`已启动 H=${horizon} Action EV；可切到运行日志查看操作记录。`);
    } catch (caught) {
      setRequestError(caught instanceof Error ? caught.message : String(caught));
    }
  };

  const cancel = async () => {
    if (!job) return;
    const data = await backendRequest<ActionJobResponseData>("action_job.cancel", {
      game_id: workspace.game_id,
      agent_id: workspace.agent_id,
      job_id: job.job_id,
    });
    setJob(data.job);
    message.info("已取消 Action EV 任务。 ");
  };

  const rows = job?.result?.rows ?? [];
  const indexedRows = useMemo(
    () => rows.map((row, index) => ({ ...row, key: `${index}-${row.strategy}` })),
    [rows],
  );
  const columns: ColumnsType<ActionEvRow & { key: string }> = [
    { title: "策略", dataIndex: "strategy", width: 180, fixed: "left", ellipsis: true },
    { title: "套装", dataIndex: "target_set", width: 140, ellipsis: true },
    { title: "位置", dataIndex: "position", width: 100 },
    { title: "主属性", dataIndex: "main_stat", width: 145, ellipsis: true },
    { title: "固定副属性", dataIndex: "fixed_substats", width: 150, ellipsis: true },
    { title: "Horizon EV", dataIndex: "horizon_ev", width: 120, render: text },
    { title: "期望提升", dataIndex: "expected_gain", width: 110, render: text },
    { title: "成型概率", dataIndex: "set_completion_probability", width: 105, render: text },
    { title: "有效/母盘", dataIndex: "effective_per_mother", width: 110, render: text },
  ];
  const progressPercent = Math.round((job?.progress_fraction ?? 0) * 1000) / 10;
  const latestLabel = text(job?.latest_event.label ?? job?.latest_event.event);
  const running = job?.status === "running";

  return (
    <section className="workspace-section calculation-section" aria-labelledby="calculation-title">
      <div className="section-heading">
        <div>
          <Typography.Title id="calculation-title" level={4}>
            Action EV 计算与性能
          </Typography.Title>
          <Typography.Text type="secondary">
            Python 精确参考引擎在独立进程运行；界面轮询进度并可安全取消
          </Typography.Text>
        </div>
        <Space>
          {running ? (
            <Button danger icon={<Square size={16} />} onClick={() => void cancel()}>
              取消
            </Button>
          ) : (
            <Tooltip title={capability.available ? "启动 Action EV" : capability.reason}>
              <span>
                <Button
                  type="primary"
                  icon={<Play size={16} />}
                  disabled={!capability.available}
                  onClick={() => void start()}
                >
                  开始计算
                </Button>
              </span>
            </Tooltip>
          )}
        </Space>
      </div>

      <Flex gap={10} align="center" wrap="wrap" className="calculation-controls">
        <Segmented
          value={horizon}
          options={[
            { value: 1, label: "H=1" },
            { value: 2, label: "H=2" },
          ]}
          onChange={(value) => setHorizon(value as 1 | 2)}
          disabled={running}
        />
        <Select
          value={actionMode}
          options={[
            { value: "fast", label: "静态调律" },
            { value: "exact", label: "深度精算" },
          ]}
          onChange={setActionMode}
          disabled={running}
          className="calculation-select"
        />
        <Select
          value={engine}
          options={[
            { value: "inventory_recursive", label: "库存递归参考引擎" },
            { value: "state_dp", label: "State DP 对照引擎" },
          ]}
          onChange={setEngine}
          disabled={running}
          className="engine-select"
        />
        {job && <Tag color={job.status === "completed" ? "success" : job.status === "failed" ? "error" : "processing"}>{job.status}</Tag>}
        {job?.horizon === 2 && job.status === "completed" && (
          <Tag color={job.elapsed_seconds <= 60 ? "success" : "warning"} icon={<Gauge size={13} />}>
            {job.elapsed_seconds.toFixed(1)} 秒 / 60 秒目标
          </Tag>
        )}
      </Flex>

      {!capability.available && (
        <Alert
          type="info"
          showIcon
          icon={<Ban size={18} />}
          message="当前不能计算"
          description={capability.reason}
          className="calculation-alert"
        />
      )}
      {requestError && (
        <Alert type="error" showIcon message="计算请求失败" description={requestError} closable />
      )}
      {job?.status === "failed" && (
        <Alert
          type="error"
          showIcon
          message="Action EV worker 失败"
          description={text(job.error?.message ?? job.error?.error_type)}
        />
      )}
      {job && (
        <div className="job-progress">
          <Progress
            percent={job.status === "completed" ? 100 : progressPercent}
            status={job.status === "failed" ? "exception" : job.status === "completed" ? "success" : "active"}
          />
          <Flex justify="space-between" gap={12}>
            <Typography.Text>{latestLabel}</Typography.Text>
            <Typography.Text type="secondary">
              {job.completed_units.toFixed(1)}/{job.total_units.toFixed(1)} 单元 · {job.elapsed_seconds.toFixed(1)} 秒
            </Typography.Text>
          </Flex>
        </div>
      )}

      {job?.result && (
        <>
          <Typography.Title level={5}>推荐结果</Typography.Title>
          <Table
            rowKey="key"
            size="small"
            columns={columns}
            dataSource={indexedRows}
            pagination={{ defaultPageSize: 20, showSizeChanger: true }}
            scroll={{ x: 1170, y: 320 }}
          />
          <Suspense fallback={<Skeleton active paragraph={{ rows: 6 }} />}>
            <PerformancePanel audit={job.result.performance_audit} />
          </Suspense>
        </>
      )}
    </section>
  );
}
