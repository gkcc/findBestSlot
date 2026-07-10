import { useMemo, useState } from "react";
import {
  App,
  Button,
  Flex,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { FilterX, Pencil, Plus, ShieldCheck, Trash2, UserRoundPlus } from "lucide-react";

import type { GearPiece, InventoryFilters, InventoryItem, Workspace } from "../types";
import {
  EMPTY_FILTERS,
  filterInventory,
  newPieceDefaults,
  positionLabel,
  targetMainStats,
} from "../workspaceUtils";
import { GearEditorDrawer } from "./GearEditorDrawer";

interface InventoryWorkspaceProps {
  workspace: Workspace;
  saving: boolean;
  mutate: (method: string, params?: Record<string, unknown>) => Promise<Workspace>;
}

interface EditorState {
  itemId: string | null;
  piece: GearPiece;
}

export function InventoryWorkspace({ workspace, saving, mutate }: InventoryWorkspaceProps) {
  const { message } = App.useApp();
  const [filters, setFilters] = useState<InventoryFilters>(EMPTY_FILTERS);
  const [editor, setEditor] = useState<EditorState | null>(null);
  const rows = useMemo(() => filterInventory(workspace, filters), [filters, workspace]);
  const allMainStats = useMemo(
    () => [...new Set(workspace.positions.flatMap((position) => position.main_stats))],
    [workspace.positions],
  );
  const loadoutCapability = workspace.capabilities.loadout_write;
  const inventoryCapability = workspace.capabilities.inventory_write;

  const savePiece = async (piece: GearPiece) => {
    if (!editor) return;
    await mutate(editor.itemId ? "inventory.update" : "inventory.create", {
      ...(editor.itemId ? { item_id: editor.itemId } : {}),
      piece,
    });
    setEditor(null);
    message.success(editor.itemId ? "库存件已更新并保存。" : "库存件已添加并保存。");
  };

  const equip = async (item: InventoryItem) => {
    await mutate("loadout.equip", { item_id: item.item_id });
    message.success(`已装备 ${item.item_id}；原同位置装备已回到全局库存。`);
  };

  const remove = async (item: InventoryItem) => {
    await mutate("inventory.delete", { item_id: item.item_id });
    message.success(`已删除 ${item.item_id}。`);
  };

  const columns: ColumnsType<InventoryItem> = [
    {
      title: "库存编号",
      dataIndex: "item_id",
      width: 150,
      fixed: "left",
      render: (value: string) => <Typography.Text code>{value}</Typography.Text>,
    },
    {
      title: "位置",
      width: 92,
      sorter: (left, right) => String(left.piece.position).localeCompare(String(right.piece.position)),
      render: (_, item) => positionLabel(workspace, item.piece.position),
    },
    {
      title: "套装",
      width: 150,
      render: (_, item) => item.piece.set_name,
    },
    {
      title: "主属性",
      width: 150,
      render: (_, item) => {
        const hit = targetMainStats(workspace, item.piece.position).includes(item.piece.main_stat);
        return (
          <Space size={5}>
            <span>{item.piece.main_stat}</span>
            {hit && <Tag color="cyan">目标</Tag>}
          </Space>
        );
      },
    },
    {
      title: "等级",
      width: 72,
      align: "center",
      render: (_, item) => `+${item.piece.level}`,
    },
    {
      title: "副属性",
      ellipsis: true,
      render: (_, item) =>
        item.piece.substats.length
          ? item.piece.substats.map((line) => `${line.stat}+${line.rolls}`).join(" / ")
          : "-",
    },
    {
      title: "归属",
      width: 155,
      render: (_, item) =>
        item.equipped_by ? (
          <Tag color={item.equipped_by.agent_id === workspace.agent_id ? "green" : "gold"}>
            {item.equipped_by.agent_name} · {item.equipped_by.position} 位
          </Tag>
        ) : (
          <Tag>背包</Tag>
        ),
    },
    {
      title: "操作",
      width: 132,
      fixed: "right",
      render: (_, item) => {
        const equippedHere = item.equipped_by?.agent_id === workspace.agent_id;
        const equippedElsewhere = Boolean(item.equipped_by && !equippedHere);
        const equipReason = !loadoutCapability.available
          ? loadoutCapability.reason
          : equippedHere
            ? "这件装备已由当前代理人装备。"
            : equippedElsewhere
              ? `这件装备正由 ${item.equipped_by?.agent_name} 使用，不能静默转移。`
              : "装备到当前代理人的对应位置";
        const deleteBlocked = item.referenced_by_snapshots > 0;
        const deleteReason = !inventoryCapability.available
          ? inventoryCapability.reason
          : deleteBlocked
            ? `仍被 ${item.referenced_by_snapshots} 个装备快照引用，不能删除。`
            : "删除库存件";
        return (
          <Space size={2}>
            <Tooltip title={equipReason}>
              <span>
                <Button
                  type="text"
                  aria-label={`装备 ${item.item_id}`}
                  icon={<UserRoundPlus size={17} />}
                  disabled={
                    saving || !loadoutCapability.available || equippedHere || equippedElsewhere
                  }
                  onClick={() => void equip(item)}
                />
              </span>
            </Tooltip>
            <Tooltip title={inventoryCapability.available ? "编辑库存件" : inventoryCapability.reason}>
              <span>
                <Button
                  type="text"
                  aria-label={`编辑 ${item.item_id}`}
                  icon={<Pencil size={16} />}
                  disabled={saving || !inventoryCapability.available}
                  onClick={() => setEditor({ itemId: item.item_id, piece: structuredClone(item.piece) })}
                />
              </span>
            </Tooltip>
            <Popconfirm
              title="删除库存件"
              description="只删除这一个 item_id；若仍被任何快照引用，后端也会拒绝。"
              okText="删除"
              cancelText="取消"
              disabled={saving || !inventoryCapability.available || deleteBlocked}
              onConfirm={() => remove(item)}
            >
              <Tooltip title={deleteReason}>
                <span>
                  <Button
                    type="text"
                    danger
                    aria-label={`删除 ${item.item_id}`}
                    icon={<Trash2 size={16} />}
                    disabled={saving || !inventoryCapability.available || deleteBlocked}
                  />
                </span>
              </Tooltip>
            </Popconfirm>
          </Space>
        );
      },
    },
  ];

  return (
    <section className="workspace-section inventory-section" aria-labelledby="inventory-title">
      <div className="section-heading">
        <div>
          <Typography.Title id="inventory-title" level={4}>
            游戏全局库存
          </Typography.Title>
          <Typography.Text type="secondary">
            显示 {rows.length}/{workspace.inventory.length} 件 · 切换代理人不会改变库存集合
          </Typography.Text>
        </div>
        <Tooltip
          title={inventoryCapability.available ? "添加库存件" : inventoryCapability.reason}
        >
          <span>
            <Button
              type="primary"
              icon={<Plus size={17} />}
              disabled={saving || !inventoryCapability.available}
              onClick={() =>
                setEditor({ itemId: null, piece: newPieceDefaults(workspace, filters) })
              }
            >
              添加库存件
            </Button>
          </span>
        </Tooltip>
      </div>

      <Flex gap={8} wrap="wrap" align="center" className="inventory-filters">
        <Select
          mode="multiple"
          allowClear
          placeholder="套装"
          value={filters.sets}
          options={workspace.sets.map((value) => ({ value, label: value }))}
          onChange={(sets) => setFilters((current) => ({ ...current, sets }))}
          className="filter-select filter-set"
          maxTagCount="responsive"
        />
        <Select
          mode="multiple"
          allowClear
          placeholder="位置"
          value={filters.positions}
          options={workspace.positions.map((position) => ({
            value: position.id,
            label: position.name,
          }))}
          onChange={(positions) => setFilters((current) => ({ ...current, positions }))}
          className="filter-select"
          maxTagCount="responsive"
        />
        <Select
          mode="multiple"
          allowClear
          showSearch
          optionFilterProp="label"
          placeholder="主属性"
          value={filters.mainStats}
          options={allMainStats.map((value) => ({ value, label: value }))}
          onChange={(mainStats) => setFilters((current) => ({ ...current, mainStats }))}
          className="filter-select filter-main"
          maxTagCount="responsive"
        />
        <Select
          value={filters.ownership}
          options={[
            { value: "all", label: "全部归属" },
            { value: "backpack", label: "只看背包" },
            { value: "equipped", label: "只看已装备" },
          ]}
          onChange={(ownership) => setFilters((current) => ({ ...current, ownership }))}
          className="ownership-select"
        />
        <Tooltip
          title={
            workspace.active_target_template
              ? "只显示命中当前代理人目标主属性的装备"
              : "当前代理人没有目标模板，无法判断目标主属性。"
          }
        >
          <Flex align="center" gap={6} className="target-main-toggle">
            <Switch
              size="small"
              checked={filters.targetMainOnly}
              disabled={!workspace.active_target_template}
              onChange={(targetMainOnly) =>
                setFilters((current) => ({ ...current, targetMainOnly }))
              }
            />
            <span>只看目标主属性</span>
          </Flex>
        </Tooltip>
        <Tooltip title="清除全部库存筛选">
          <Button
            type="text"
            aria-label="清除全部筛选"
            icon={<FilterX size={17} />}
            disabled={JSON.stringify(filters) === JSON.stringify(EMPTY_FILTERS)}
            onClick={() => setFilters(EMPTY_FILTERS)}
          />
        </Tooltip>
        {workspace.canonical_inventory && (
          <Tag icon={<ShieldCheck size={13} />} color="success">
            item_id 全局库存
          </Tag>
        )}
      </Flex>

      <Table
        rowKey="item_id"
        size="small"
        columns={columns}
        dataSource={rows}
        pagination={{ defaultPageSize: 50, showSizeChanger: true, pageSizeOptions: [25, 50, 100] }}
        scroll={{ x: 1180, y: "calc(100vh - 395px)" }}
        locale={{ emptyText: "没有符合筛选条件的库存件" }}
      />

      {editor && (
        <GearEditorDrawer
          open
          workspace={workspace}
          initialPiece={editor.piece}
          title={editor.itemId ? `编辑库存件 ${editor.itemId}` : "新增库存件"}
          saving={saving}
          onClose={() => setEditor(null)}
          onSave={savePiece}
        />
      )}
    </section>
  );
}
