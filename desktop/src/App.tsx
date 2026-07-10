import { lazy, Suspense, useState } from "react";
import {
  Alert,
  App as AntApp,
  Button,
  Flex,
  Layout,
  Popconfirm,
  Result,
  Select,
  Skeleton,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import { CircleCheck, Gauge, Pencil, RefreshCw, ScrollText, Target, Trash2 } from "lucide-react";

import { AgentAvatar } from "./components/AgentAvatar";
import { CurrentLoadout } from "./components/CurrentLoadout";
import { InventoryWorkspace } from "./components/InventoryWorkspace";
import { TargetTemplateDrawer } from "./components/TargetTemplateDrawer";
import { useWorkspace } from "./hooks/useWorkspace";
import type { CharacterPreset } from "./types";

const CalculationWorkspace = lazy(() => import("./components/CalculationWorkspace"));
const LogsWorkspace = lazy(() => import("./components/LogsWorkspace"));

function OptimizerWorkspace() {
  const { message } = AntApp.useApp();
  const controller = useWorkspace();
  const [activeTab, setActiveTab] = useState("current");
  const [templateEditorOpen, setTemplateEditorOpen] = useState(false);
  const workspace = controller.workspace;

  if (controller.loading && !workspace) {
    return (
      <main className="app-loading">
        <Skeleton active paragraph={{ rows: 12 }} />
      </main>
    );
  }
  if (!workspace) {
    return (
      <Result
        status="error"
        title="工作区载入失败"
        subTitle={controller.error || "本地后端没有返回工作区。"}
        extra={
          <Button
            type="primary"
            icon={<RefreshCw size={16} />}
            onClick={() => void controller.reload()}
          >
            重试
          </Button>
        }
      />
    );
  }

  const selectedAgent = workspace.agents.find((agent) => agent.agent_id === workspace.agent_id);
  const selectedTemplate = workspace.target_templates.find(
    (template) => template.id === workspace.active_target_template_id,
  );
  const saveTemplate = async (template: CharacterPreset, label: string) => {
    await controller.mutate("target_template.save", { template, label });
    setTemplateEditorOpen(false);
    message.success("目标模板已保存，并只绑定当前代理人。 ");
  };
  const deleteTemplate = async () => {
    if (!workspace.active_target_template_id) return;
    await controller.mutate("target_template.delete", {
      template_id: workspace.active_target_template_id,
    });
    message.success(selectedTemplate?.builtin ? "内置模板已从当前设备隐藏。" : "自定义模板已删除。");
  };

  return (
    <Layout className="app-shell">
      <header className="app-header">
        <div className="brand-block">
          <div className="brand-mark">BOX</div>
          <div>
            <Typography.Title level={3}>装备优化器</Typography.Title>
            <Typography.Text type="secondary">本地库存与代理人装备工作台</Typography.Text>
          </div>
        </div>

        <Flex align="center" gap={10} wrap="wrap" className="context-controls">
          <div className="context-field">
            <Typography.Text type="secondary">游戏</Typography.Text>
            <Select
              aria-label="选择游戏"
              value={workspace.game_id}
              options={workspace.games.map((game) => ({ value: game.id, label: game.name }))}
              onChange={(gameId) => void controller.reload(gameId)}
              className="game-select"
              loading={controller.loading}
            />
          </div>
          <div className="context-field agent-context-field">
            <Typography.Text type="secondary">代理人</Typography.Text>
            <Select
              aria-label="选择代理人"
              value={workspace.agent_id}
              optionLabelProp="label"
              options={workspace.agents.map((agent) => ({
                value: agent.agent_id,
                label: agent.name,
                search: `${agent.name} ${agent.attribute} ${agent.specialty}`,
              }))}
              optionRender={(option) => {
                const agent = workspace.agents.find(
                  (candidate) => candidate.agent_id === option.value,
                );
                return agent ? (
                  <Flex gap={8} align="center">
                    <AgentAvatar name={agent.name} path={agent.portrait_path} size={30} />
                    <div>
                      <div>{agent.name}</div>
                      <Typography.Text type="secondary">
                        {agent.attribute} · {agent.specialty}
                      </Typography.Text>
                    </div>
                  </Flex>
                ) : null;
              }}
              showSearch
              filterOption={(input, option) =>
                String(option?.search ?? "").toLowerCase().includes(input.toLowerCase())
              }
              onChange={(agentId) => void controller.reload(workspace.game_id, agentId)}
              className="agent-select"
              loading={controller.loading}
            />
          </div>
          <div className="context-field template-context-field">
            <Typography.Text type="secondary">目标模板</Typography.Text>
            <Flex gap={4}>
              <Select
                aria-label="选择目标模板"
                value={workspace.active_target_template_id ?? undefined}
                placeholder="尚未创建目标模板"
                options={workspace.target_templates.map((template) => ({
                  value: template.id,
                  label: `${template.builtin ? "内置" : "自定义"} · ${template.name}`,
                }))}
                onChange={(templateId) =>
                  void controller.mutate("target_template.select", { template_id: templateId })
                }
                className="template-select"
                notFoundContent="当前代理人没有目标模板"
              />
              <Tooltip title={selectedTemplate ? "编辑；内置模板会另存为当前代理人的自定义模板" : "创建当前代理人的目标模板"}>
                <Button
                  aria-label={selectedTemplate ? "编辑目标模板" : "创建目标模板"}
                  icon={selectedTemplate ? <Pencil size={16} /> : <Target size={17} />}
                  onClick={() => setTemplateEditorOpen(true)}
                />
              </Tooltip>
              {selectedTemplate && (
                <Popconfirm
                  title={selectedTemplate.builtin ? "隐藏内置模板" : "删除目标模板"}
                  description="不会删除全局库存或当前装备。"
                  okText={selectedTemplate.builtin ? "隐藏" : "删除"}
                  cancelText="取消"
                  onConfirm={deleteTemplate}
                >
                  <Tooltip title={selectedTemplate.builtin ? "隐藏这个内置模板" : "删除这个自定义模板"}>
                    <Button
                      danger
                      aria-label="删除或隐藏目标模板"
                      icon={<Trash2 size={16} />}
                    />
                  </Tooltip>
                </Popconfirm>
              )}
            </Flex>
          </div>
        </Flex>
      </header>

      <div className="agent-strip">
        <Flex align="center" gap={10}>
          <AgentAvatar
            name={selectedAgent?.name ?? workspace.agent_id}
            path={selectedAgent?.portrait_path}
            size={42}
          />
          <div>
            <Typography.Text strong>{selectedAgent?.name ?? workspace.agent_id}</Typography.Text>
            <div className="agent-meta">
              {selectedAgent && `${selectedAgent.rarity} · ${selectedAgent.attribute} · ${selectedAgent.specialty} · ${selectedAgent.faction}`}
            </div>
          </div>
        </Flex>
        <Flex align="center" gap={8} wrap="wrap">
          <Tag color={workspace.canonical_inventory ? "success" : "warning"}>
            {workspace.canonical_inventory ? "全局 item_id 库存" : "旧格式只读"}
          </Tag>
          <Tag>{workspace.inventory.length} 件库存</Tag>
          <Tag>
            {workspace.current_loadout.slots.filter((slot) => slot.item_id).length}/
            {workspace.current_loadout.slots.length} 件当前装备
          </Tag>
          <span className="save-status">
            {controller.saving ? (
              "正在保存..."
            ) : (
              <>
                <CircleCheck size={14} />
                {controller.lastSavedAt ? "已自动保存" : "已载入"}
              </>
            )}
          </span>
        </Flex>
      </div>

      {controller.error && (
        <Alert
          type="error"
          showIcon
          closable
          message="操作没有完成"
          description={controller.error}
          action={
            <Button size="small" onClick={() => void controller.reload(workspace.game_id, workspace.agent_id)}>
              重新载入
            </Button>
          }
          className="workspace-alert"
        />
      )}

      <main className="workspace-main">
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          items={[
            {
              key: "current",
              label: "当前装备",
              children: (
                <CurrentLoadout
                  workspace={workspace}
                  saving={controller.saving}
                  onUnequip={async (position) => {
                    await controller.mutate("loadout.unequip", { position });
                    message.success("已卸下装备；同一 item_id 仍保留在全局库存。 ");
                  }}
                />
              ),
            },
            {
              key: "inventory",
              label: `全局库存 (${workspace.inventory.length})`,
              children: (
                <InventoryWorkspace
                  workspace={workspace}
                  saving={controller.saving}
                  mutate={controller.mutate}
                />
              ),
            },
            {
              key: "calculation",
              label: (
                <span className="tab-label">
                  <Gauge size={15} />计算与性能
                </span>
              ),
              children: (
                <Suspense fallback={<Skeleton active paragraph={{ rows: 10 }} />}>
                  <CalculationWorkspace workspace={workspace} />
                </Suspense>
              ),
            },
            {
              key: "logs",
              label: (
                <span className="tab-label">
                  <ScrollText size={15} />运行日志
                </span>
              ),
              children: (
                <Suspense fallback={<Skeleton active paragraph={{ rows: 10 }} />}>
                  <LogsWorkspace workspace={workspace} />
                </Suspense>
              ),
            },
          ]}
        />
      </main>

      {templateEditorOpen && (
        <TargetTemplateDrawer
          open
          workspace={workspace}
          saving={controller.saving}
          onClose={() => setTemplateEditorOpen(false)}
          onSave={saveTemplate}
        />
      )}
    </Layout>
  );
}

export default function App() {
  return <OptimizerWorkspace />;
}
