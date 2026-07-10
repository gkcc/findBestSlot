import { useEffect } from "react";
import {
  Button,
  Divider,
  Drawer,
  Flex,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Typography,
} from "antd";
import { Plus, Save, Trash2 } from "lucide-react";

import type { CharacterPreset, Workspace } from "../types";

interface RequirementFormValue {
  set_name: string;
  pieces: number;
}

interface TemplateFormValues {
  name: string;
  target_set: string;
  requirements: RequirementFormValue[];
  preferred: Record<string, string[]>;
  core: string[];
  usable: string[];
  target_effective_rolls: number;
  notes?: string;
}

interface TargetTemplateDrawerProps {
  open: boolean;
  workspace: Workspace;
  saving: boolean;
  onClose: () => void;
  onSave: (template: CharacterPreset, label: string) => Promise<void>;
}

function formValues(workspace: Workspace): TemplateFormValues {
  const template = workspace.active_target_template;
  const activePlan = template?.set_plans.find(
    (plan) => plan.id === template.default_set_plan,
  ) ?? template?.set_plans[0];
  const requirements = activePlan?.requirements.map((requirement) => ({
    set_name: requirement.set_name ?? requirement.set_names?.[0] ?? workspace.sets[0],
    pieces: requirement.pieces,
  })) ?? [{ set_name: workspace.sets[0], pieces: Math.min(4, workspace.positions.length) }];
  return {
    name: template?.name ?? "",
    target_set: template?.target_set ?? workspace.sets[0],
    requirements,
    preferred: template?.preferred_main_stats ?? {},
    core: template?.substat_priority?.core ?? [],
    usable: template?.substat_priority?.usable ?? [],
    target_effective_rolls: template?.target_effective_rolls ?? 6,
    notes: template?.notes ?? "",
  };
}

export function TargetTemplateDrawer({
  open,
  workspace,
  saving,
  onClose,
  onSave,
}: TargetTemplateDrawerProps) {
  const [form] = Form.useForm<TemplateFormValues>();

  useEffect(() => {
    if (open) form.setFieldsValue(formValues(workspace));
  }, [form, open, workspace]);

  const finish = async (values: TemplateFormValues) => {
    const requirementTotal = values.requirements.reduce(
      (total, requirement) => total + requirement.pieces,
      0,
    );
    if (requirementTotal > workspace.positions.length) {
      form.setFields([
        {
          name: "requirements",
          errors: [`套装方案共 ${requirementTotal} 件，超过 ${workspace.positions.length} 个位置。`],
        },
      ]);
      return;
    }
    const core = values.core ?? [];
    const usable = (values.usable ?? []).filter((stat) => !core.includes(stat));
    const planId = "desktop_primary";
    const existing = workspace.active_target_template;
    const template: CharacterPreset = {
      id: existing?.id ?? `draft_${workspace.agent_id}`,
      game: workspace.game_id,
      name: values.name,
      target_set: values.target_set,
      effective_substats: Object.fromEntries([...core, ...usable].map((stat) => [stat, 1])),
      substat_priority: { core, usable },
      preferred_main_stats: Object.fromEntries(
        Object.entries(values.preferred ?? {}).filter(([, stats]) => stats.length > 0),
      ),
      set_plans: values.requirements.length
        ? [
            {
              id: planId,
              name: "目标套装方案",
              requirements: values.requirements.map((requirement, index) => ({
                set_name: requirement.set_name,
                pieces: requirement.pieces,
                priority: index + 1,
              })),
            },
          ]
        : [],
      default_set_plan: values.requirements.length ? planId : null,
      target_effective_rolls: values.target_effective_rolls,
      rating_thresholds: existing?.rating_thresholds ?? {
        usable: 2,
        good: 4,
        excellent: 6,
      },
      notes: values.notes || null,
    };
    await onSave(template, values.name);
  };

  return (
    <Drawer
      title={workspace.active_target_template ? "编辑目标模板" : "创建目标模板"}
      width={620}
      open={open}
      onClose={onClose}
      destroyOnHidden
      extra={
        <Button
          type="primary"
          icon={<Save size={16} />}
          loading={saving}
          onClick={() => form.submit()}
        >
          保存模板
        </Button>
      }
    >
      <Form form={form} layout="vertical" onFinish={finish}>
        <Flex gap={12} wrap="wrap">
          <Form.Item
            name="name"
            label="模板名称"
            rules={[{ required: true, whitespace: true, message: "请输入模板名称" }]}
            className="field-grow"
          >
            <Input placeholder="例如：叶瞬光毕业目标" />
          </Form.Item>
          <Form.Item
            name="target_set"
            label="主目标套装"
            rules={[{ required: true, message: "请选择主目标套装" }]}
            className="field-grow"
          >
            <Select
              showSearch
              optionFilterProp="label"
              options={workspace.sets.map((value) => ({ value, label: value }))}
            />
          </Form.Item>
        </Flex>

        <Typography.Title level={5}>套装方案</Typography.Title>
        <Form.List name="requirements">
          {(fields, { add, remove }) => (
            <Space direction="vertical" size={8} className="full-width">
              {fields.map((field) => (
                <Flex key={field.key} gap={8} align="center">
                  <Form.Item
                    {...field}
                    name={[field.name, "set_name"]}
                    rules={[{ required: true, message: "请选择套装" }]}
                    className="requirement-set"
                  >
                    <Select
                      showSearch
                      optionFilterProp="label"
                      options={workspace.sets.map((value) => ({ value, label: value }))}
                    />
                  </Form.Item>
                  <Form.Item
                    {...field}
                    name={[field.name, "pieces"]}
                    rules={[{ required: true, message: "必填" }]}
                    className="requirement-count"
                  >
                    <InputNumber min={1} max={workspace.positions.length} addonAfter="件" />
                  </Form.Item>
                  <Button
                    type="text"
                    danger
                    aria-label="删除套装要求"
                    title="删除套装要求"
                    icon={<Trash2 size={16} />}
                    onClick={() => remove(field.name)}
                  />
                </Flex>
              ))}
              <Button
                type="dashed"
                icon={<Plus size={16} />}
                onClick={() => add({ set_name: workspace.sets[0], pieces: 2 })}
                block
              >
                添加套装要求
              </Button>
            </Space>
          )}
        </Form.List>

        <Divider />
        <Typography.Title level={5}>各位置目标主属性</Typography.Title>
        <div className="preferred-main-grid">
          {workspace.positions.map((position) => (
            <Form.Item
              key={position.id}
              name={["preferred", position.id]}
              label={position.name}
            >
              <Select
                mode="multiple"
                allowClear
                placeholder="不限"
                options={position.main_stats.map((value) => ({ value, label: value }))}
              />
            </Form.Item>
          ))}
        </div>

        <Divider />
        <Flex gap={12} wrap="wrap">
          <Form.Item name="core" label="核心副属性" className="field-grow">
            <Select
              mode="multiple"
              allowClear
              options={workspace.sub_stats.map((value) => ({ value, label: value }))}
            />
          </Form.Item>
          <Form.Item name="usable" label="可用副属性" className="field-grow">
            <Select
              mode="multiple"
              allowClear
              options={workspace.sub_stats.map((value) => ({ value, label: value }))}
            />
          </Form.Item>
        </Flex>
        <Form.Item name="target_effective_rolls" label="目标有效强化次数">
          <InputNumber min={0} max={20} step={0.5} />
        </Form.Item>
        <Form.Item name="notes" label="备注">
          <Input.TextArea autoSize={{ minRows: 2, maxRows: 5 }} />
        </Form.Item>
      </Form>
    </Drawer>
  );
}
