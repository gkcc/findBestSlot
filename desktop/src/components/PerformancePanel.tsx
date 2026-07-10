import { useEffect, useMemo, useRef } from "react";
import { BarChart, HeatmapChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  VisualMapComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { Empty, Statistic, Table, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";

import type { ActionEvPerformanceAudit } from "../types";

echarts.use([
  BarChart,
  HeatmapChart,
  GridComponent,
  TooltipComponent,
  VisualMapComponent,
  CanvasRenderer,
]);

interface PerformancePanelProps {
  audit: ActionEvPerformanceAudit;
}

interface SlowActionRow {
  key: string;
  label: string;
  seconds: number;
  raw_outcome_count: number;
  best_loadout_value_calls: number;
}

function numeric(value: unknown): number {
  const parsed = Number(value ?? 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

export default function PerformancePanel({ audit }: PerformancePanelProps) {
  const phaseChartRef = useRef<HTMLDivElement>(null);
  const heatmapRef = useRef<HTMLDivElement>(null);
  const phaseEntries = useMemo(
    () => Object.entries(audit.phase_seconds).sort((left, right) => right[1] - left[1]),
    [audit.phase_seconds],
  );
  const slowPhaseCalls = audit.top_20_slowest_phase_calls ?? [];

  useEffect(() => {
    const container = phaseChartRef.current;
    if (!container || !phaseEntries.length) return;
    const chart = echarts.init(container);
    chart.setOption({
      animation: false,
      tooltip: { trigger: "axis", valueFormatter: (value: unknown) => `${numeric(value).toFixed(3)} 秒` },
      grid: { left: 165, right: 24, top: 16, bottom: 30 },
      xAxis: { type: "value", name: "秒" },
      yAxis: {
        type: "category",
        inverse: true,
        data: phaseEntries.map(([phase]) => phase),
        axisLabel: { width: 150, overflow: "truncate" },
      },
      series: [
        {
          type: "bar",
          data: phaseEntries.map(([, seconds]) => seconds),
          itemStyle: { color: "#087f78" },
          barMaxWidth: 18,
        },
      ],
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(container);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [phaseEntries]);

  useEffect(() => {
    const container = heatmapRef.current;
    if (!container || !slowPhaseCalls.length) return;
    const phases = [...new Set(slowPhaseCalls.map((call) => String(call.phase ?? "unknown")))];
    const data = slowPhaseCalls.map((call, index) => [
      index,
      phases.indexOf(String(call.phase ?? "unknown")),
      numeric(call.seconds),
    ]);
    const maximum = Math.max(...data.map((item) => item[2]), 0.001);
    const chart = echarts.init(container);
    chart.setOption({
      animation: false,
      tooltip: {
        position: "top",
        formatter: (params: { value?: unknown[] }) => {
          const value = params.value ?? [];
          return `${phases[numeric(value[1])] ?? "unknown"}<br/>${numeric(value[2]).toFixed(4)} 秒`;
        },
      },
      grid: { left: 150, right: 24, top: 18, bottom: 54 },
      xAxis: {
        type: "category",
        data: slowPhaseCalls.map((_, index) => `#${index + 1}`),
        splitArea: { show: true },
      },
      yAxis: {
        type: "category",
        data: phases,
        splitArea: { show: true },
        axisLabel: { width: 135, overflow: "truncate" },
      },
      visualMap: {
        min: 0,
        max: maximum,
        calculable: false,
        orient: "horizontal",
        left: "center",
        bottom: 0,
        inRange: { color: ["#e6f1ef", "#e5a521", "#bd3030"] },
      },
      series: [{ type: "heatmap", data, emphasis: { itemStyle: { borderColor: "#263b44" } } }],
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(container);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [slowPhaseCalls]);

  const slowActions: SlowActionRow[] = (audit.top_10_slowest_actions ?? []).map(
    (row, index) => ({
      key: `${index}-${String(row.label ?? row.strategy ?? "action")}`,
      label: String(row.label ?? row.strategy ?? "-"),
      seconds: numeric(row.seconds),
      raw_outcome_count: numeric(row.raw_outcome_count),
      best_loadout_value_calls: numeric(row.best_loadout_value_calls),
    }),
  );
  const columns: ColumnsType<SlowActionRow> = [
    { title: "Action", dataIndex: "label", ellipsis: true },
    { title: "耗时（秒）", dataIndex: "seconds", width: 110, render: (value) => value.toFixed(3) },
    { title: "原始 outcome", dataIndex: "raw_outcome_count", width: 120 },
    { title: "Best 调用", dataIndex: "best_loadout_value_calls", width: 110 },
  ];

  return (
    <div className="performance-panel">
      <div className="performance-metrics">
        <Statistic title="总耗时" value={audit.total_seconds} precision={2} suffix="秒" />
        <Statistic title="Action" value={audit.action_count} />
        <Statistic title="原始 outcome" value={audit.raw_outcome_count} />
        <Statistic title="聚合 outcome" value={audit.aggregated_outcome_count} />
        <Statistic title="Best 调用" value={audit.best_loadout_value_calls} />
        <Statistic
          title="Best 缓存命中率"
          value={
            audit.best_loadout_value_calls
              ? (audit.best_loadout_cache_hits / audit.best_loadout_value_calls) * 100
              : 0
          }
          precision={1}
          suffix="%"
        />
      </div>

      <div className="chart-grid">
        <section>
          <Typography.Title level={5}>阶段累计耗时</Typography.Title>
          {phaseEntries.length ? <div ref={phaseChartRef} className="performance-chart" /> : <Empty />}
        </section>
        <section>
          <Typography.Title level={5}>最慢阶段调用热力图</Typography.Title>
          {slowPhaseCalls.length ? <div ref={heatmapRef} className="performance-chart" /> : <Empty />}
        </section>
      </div>

      <Typography.Title level={5}>最慢 Action</Typography.Title>
      <Table
        size="small"
        rowKey="key"
        columns={columns}
        dataSource={slowActions}
        pagination={false}
        locale={{ emptyText: "性能审计没有记录 Action 明细" }}
        scroll={{ x: 720 }}
      />
    </div>
  );
}
