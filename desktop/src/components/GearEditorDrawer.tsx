import { useEffect, useMemo } from "react";
import {
  Button,
  Drawer,
  Flex,
  Form,
  InputNumber,
  Select,
  Space,
  Switch,
  Typography,
} from "antd";
import { Plus, Save, Trash2 } from "lucide-react";

import type { GearPiece, Workspace } from "../types";

interface GearEditorDrawerProps {
  open: boolean;
  workspace: Workspace;
  initialPiece: GearPiece;
  title: string;
  saving: boolean;
  onClose: () => void;
  onSave: (piece: GearPiece) => Promise<void>;
}

export function GearEditorDrawer({
  open,
  workspace,
  initialPiece,
  title,
  saving,
  onClose,
  onSave,
}: GearEditorDrawerProps) {
  const [form] = Form.useForm<GearPiece>();
  const position = String(Form.useWatch("position", form) ?? initialPiece.position);
  const mainStat = Form.useWatch("main_stat", form) ?? initialPiece.main_stat;
  const positionRule = useMemo(
    () => workspace.positions.find((candidate) => candidate.id === position) ?? workspace.positions[0],
    [position, workspace.positions],
  );

  useEffect(() => {
    if (open) form.setFieldsValue(structuredClone(initialPiece));
  }, [form, initialPiece, open]);

  const updateDependentFields = (nextPosition: string) => {
    const rule = workspace.positions.find((candidate) => candidate.id === nextPosition);
    if (!rule) return;
    const currentSet = form.getFieldValue("set_name");
    const currentMain = form.getFieldValue("main_stat");
    form.setFieldsValue({
      set_name: rule.set_names.includes(currentSet) ? currentSet : rule.set_names[0],
      main_stat: rule.main_stats.includes(currentMain) ? currentMain : rule.main_stats[0],
    });
  };

  return (
    <Drawer
      title={title}
      width={520}
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
          保存
        </Button>
      }
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={initialPiece}
        onFinish={(values) => onSave({ ...values, position: String(values.position) })}
      >
        <Flex gap={12} wrap="wrap">
          <Form.Item
            name="position"
            label="位置"
            rules={[{ required: true, message: "请选择位置" }]}
            className="field-grow"
          >
            <Select
              options={workspace.positions.map((item) => ({
                value: item.id,
                label: item.name,
              }))}
              onChange={updateDependentFields}
            />
          </Form.Item>
          <Form.Item
            name="set_name"
            label="套装"
            rules={[{ required: true, message: "请选择套装" }]}
            className="field-grow"
          >
            <Select
              showSearch
              optionFilterProp="label"
              options={positionRule.set_names.map((value) => ({ value, label: value }))}
            />
          </Form.Item>
        </Flex>

        <Flex gap={12} wrap="wrap">
          <Form.Item
            name="main_stat"
            label="主属性"
            rules={[{ required: true, message: "请选择主属性" }]}
            className="field-grow"
          >
            <Select
              showSearch
              optionFilterProp="label"
              options={positionRule.main_stats.map((value) => ({ value, label: value }))}
            />
          </Form.Item>
          <Form.Item name="level" label="强化等级" className="field-compact">
            <Select
              options={Array.from(
                { length: workspace.max_level / workspace.level_step + 1 },
                (_, index) => ({
                  value: index * workspace.level_step,
                  label: `+${index * workspace.level_step}`,
                }),
              )}
            />
          </Form.Item>
          <Form.Item name="initial_substat_count" label="初始副属性" className="field-compact">
            <Select
              options={[
                { value: 3, label: "3 条" },
                { value: 4, label: "4 条" },
              ]}
            />
          </Form.Item>
        </Flex>

        <Flex align="center" gap={8} className="switch-row">
          <Form.Item name="locked" valuePropName="checked" noStyle>
            <Switch />
          </Form.Item>
          <Typography.Text>锁定这件装备</Typography.Text>
        </Flex>

        <Typography.Title level={5}>副属性</Typography.Title>
        <Form.List name="substats">
          {(fields, { add, remove }) => (
            <Space direction="vertical" size={8} className="full-width">
              {fields.map((field) => (
                <Flex key={field.key} gap={8} align="center">
                  <Form.Item
                    {...field}
                    name={[field.name, "stat"]}
                    rules={[{ required: true, message: "请选择副属性" }]}
                    className="substat-name"
                  >
                    <Select
                      showSearch
                      optionFilterProp="label"
                      options={workspace.sub_stats
                        .filter((value) => value !== mainStat)
                        .map((value) => ({ value, label: value }))}
                    />
                  </Form.Item>
                  <Form.Item
                    {...field}
                    name={[field.name, "rolls"]}
                    rules={[{ required: true, message: "必填" }]}
                    className="substat-rolls"
                  >
                    <InputNumber min={0} max={5} addonAfter="次" />
                  </Form.Item>
                  <Button
                    type="text"
                    danger
                    aria-label="删除副属性"
                    title="删除副属性"
                    icon={<Trash2 size={16} />}
                    onClick={() => remove(field.name)}
                  />
                </Flex>
              ))}
              {fields.length < 4 && (
                <Button
                  type="dashed"
                  icon={<Plus size={16} />}
                  onClick={() => add({ stat: "", rolls: 0 })}
                  block
                >
                  添加副属性
                </Button>
              )}
            </Space>
          )}
        </Form.List>
      </Form>
    </Drawer>
  );
}
