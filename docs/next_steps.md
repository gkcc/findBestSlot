# Next Steps

以下不是当前交付的阻塞项，只是后续继续优化时需要人工决策或手动重型验证的事项。

1. 在真实大库存上手动运行 `horizon=2` 长任务，观察窗口拖动、切 tab、取消后的旧结果保留体验是否符合预期。
2. 如后续继续做性能优化，先运行 `python -m gear_optimizer.profile_action_ev --horizon 2 --output reports\action_ev_profile_h2.json --summary reports\action_ev_profile_h2_summary.md`，再决定是否做严格等价剪枝。
3. 若要把强化材料折算进推荐排序，需要先确定校音器、共鸣核以外的强化资源价值模型；当前 UI 只解释“不折算强化材料”。
