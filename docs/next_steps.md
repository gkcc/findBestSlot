# Next Steps

以下不是当前交付的阻塞项，只记录确实需要人工决策或手动重型验证的事项。

1. 在真实大库存上手动运行 `horizon=2` 长任务，观察窗口拖动、切 tab、取消后的旧结果保留体验是否符合预期。
2. 运行真实大库存的 state-DP profile，例如 `python -m gear_optimizer.profile_action_ev --horizon 2 --state-dp --output reports\action_ev_profile_h2_state_dp.json --summary reports\action_ev_profile_h2_state_dp_summary.md`，再决定是否把 `use_state_dp=True` 作为桌面默认引擎。
3. 如果大样本显示 state DP 有收益，再评估是否把可选进程池并行接入 UI，并提供 worker 数设置；当前 `GEAR_OPTIMIZER_WORKERS` 只用于诊断/帮助函数路径。
4. 若要把强化材料折算进推荐排序，需要先确定校音器、共鸣核以外的强化资源价值模型；当前 UI 只解释“不折算强化材料”。
