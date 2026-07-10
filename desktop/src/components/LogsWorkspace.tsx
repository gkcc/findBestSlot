import { useCallback, useEffect, useState } from "react";
import { App, Button, Flex, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { Copy, FileArchive, RefreshCw } from "lucide-react";

import { backendRequest } from "../api";
import type { RuntimeEvent, Workspace } from "../types";

interface LogsWorkspaceProps {
  workspace: Workspace;
}

interface LogRow extends RuntimeEvent {
  key: string;
}

function display(value: unknown): string {
  return value === null || value === undefined || value === "" ? "-" : String(value);
}

export default function LogsWorkspace({ workspace }: LogsWorkspaceProps) {
  const { message } = App.useApp();
  const [events, setEvents] = useState<RuntimeEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [diagnosticPath, setDiagnosticPath] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await backendRequest<{ events: RuntimeEvent[] }>("logs.tail", {
        limit: 300,
      });
      setEvents(data.events);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const exportDiagnostics = async () => {
    try {
      const data = await backendRequest<{ path: string }>("diagnostics.export", {
        game_id: workspace.game_id,
        agent_id: workspace.agent_id,
      });
      setDiagnosticPath(data.path);
      message.success("诊断包已写入本机。 ");
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  };

  const rows: LogRow[] = events
    .map((event, index) => ({ ...event, key: `${event.ts ?? "time"}-${index}` }))
    .reverse();
  const columns: ColumnsType<LogRow> = [
    { title: "时间", dataIndex: "ts", width: 175, render: display },
    { title: "来源", dataIndex: "source", width: 135, render: display },
    {
      title: "事件/命令",
      width: 230,
      render: (_, row) => row.method ?? row.event ?? "-",
    },
    { title: "代理人", dataIndex: "agent_id", width: 175, render: display },
    {
      title: "结果",
      width: 110,
      render: (_, row) => {
        const result = row.error_code ? "error" : display(row.result);
        return result === "-" ? "-" : <Tag color={result === "ok" ? "success" : "error"}>{result}</Tag>;
      },
    },
    {
      title: "耗时（秒）",
      dataIndex: "elapsed_seconds",
      width: 110,
      render: (value) => (value === undefined ? "-" : Number(value).toFixed(3)),
    },
    {
      title: "详情",
      ellipsis: true,
      render: (_, row) => display(row.error_message ?? row.job_id ?? row.output_path),
    },
  ];

  return (
    <section className="workspace-section logs-section" aria-labelledby="logs-title">
      <div className="section-heading">
        <div>
          <Typography.Title id="logs-title" level={4}>
            运行日志与诊断
          </Typography.Title>
          <Typography.Text type="secondary">
            选择、保存、装备、计算、取消和失败均写入本地滚动 JSONL
          </Typography.Text>
        </div>
        <Flex gap={8}>
          <Button icon={<RefreshCw size={16} />} loading={loading} onClick={() => void refresh()}>
            刷新
          </Button>
          <Button type="primary" icon={<FileArchive size={16} />} onClick={() => void exportDiagnostics()}>
            导出诊断包
          </Button>
        </Flex>
      </div>

      {error && <Typography.Text type="danger">{error}</Typography.Text>}
      {diagnosticPath && (
        <Flex align="center" gap={8} className="diagnostic-path">
          <Typography.Text code>{diagnosticPath}</Typography.Text>
          <Button
            type="text"
            aria-label="复制诊断包路径"
            icon={<Copy size={16} />}
            onClick={() => {
              void navigator.clipboard.writeText(diagnosticPath);
              message.success("诊断包路径已复制。 ");
            }}
          />
        </Flex>
      )}
      <Table
        size="small"
        rowKey="key"
        columns={columns}
        dataSource={rows}
        loading={loading && !events.length}
        pagination={{ defaultPageSize: 50, showSizeChanger: true }}
        scroll={{ x: 1100, y: "calc(100vh - 340px)" }}
        locale={{ emptyText: "还没有运行事件" }}
      />
    </section>
  );
}
