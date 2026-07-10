import { Button, Empty, Tag, Tooltip, Typography } from "antd";
import { LockKeyhole, PackageOpen, Unplug } from "lucide-react";

import type { Workspace } from "../types";
import { pieceSummary } from "../workspaceUtils";

interface CurrentLoadoutProps {
  workspace: Workspace;
  saving: boolean;
  onUnequip: (position: string) => Promise<void>;
}

export function CurrentLoadout({ workspace, saving, onUnequip }: CurrentLoadoutProps) {
  const capability = workspace.capabilities.loadout_write;
  const filled = workspace.current_loadout.slots.filter((slot) => slot.item_id).length;
  return (
    <section className="workspace-section" aria-labelledby="current-loadout-title">
      <div className="section-heading">
        <div>
          <Typography.Title id="current-loadout-title" level={4}>
            当前装备
          </Typography.Title>
          <Typography.Text type="secondary">
            {filled}/{workspace.current_loadout.slots.length} 件 · 装备和卸下会即时保存
          </Typography.Text>
        </div>
        <Tag color={workspace.current_loadout.complete ? "success" : "warning"}>
          {workspace.current_loadout.complete ? "盘面完整" : "盘面未补齐"}
        </Tag>
      </div>

      <div className="loadout-grid">
        {workspace.current_loadout.slots.map((slot) => {
          const item = slot.item;
          return (
            <article className={`loadout-slot ${item ? "is-filled" : "is-empty"}`} key={slot.position}>
              <div className="slot-heading">
                <span className="slot-index">{slot.position}</span>
                <Typography.Text strong>{slot.position_name}</Typography.Text>
                {item?.piece.locked && (
                  <Tooltip title="这件装备已锁定">
                    <LockKeyhole size={15} aria-label="已锁定" />
                  </Tooltip>
                )}
              </div>
              {item ? (
                <>
                  <Typography.Text className="piece-set">{item.piece.set_name}</Typography.Text>
                  <Typography.Text>{item.piece.main_stat}</Typography.Text>
                  <Typography.Text type="secondary" className="piece-detail">
                    {pieceSummary(item)}
                  </Typography.Text>
                  <div className="slot-footer">
                    <Typography.Text code>{item.item_id}</Typography.Text>
                    <Tooltip title={capability.available ? "卸下并放回全局库存" : capability.reason}>
                      <span>
                        <Button
                          type="text"
                          danger
                          aria-label={`卸下${slot.position_name}`}
                          icon={<Unplug size={17} />}
                          disabled={!capability.available || saving}
                          onClick={() => void onUnequip(slot.position)}
                        />
                      </span>
                    </Tooltip>
                  </div>
                </>
              ) : (
                <Empty
                  image={<PackageOpen size={28} />}
                  description="未装备"
                  className="slot-empty-state"
                />
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}
