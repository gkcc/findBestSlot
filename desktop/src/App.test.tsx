import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App as AntApp, ConfigProvider } from "antd";
import { beforeEach, describe, expect, it } from "vitest";

import App from "./App";
import { resetMockBackend } from "./mockBackend";

function renderApp() {
  return render(
    <ConfigProvider>
      <AntApp>
        <App />
      </AntApp>
    </ConfigProvider>,
  );
}

describe("maintenance workspace", () => {
  beforeEach(() => resetMockBackend());

  it("shows normal game, agent, and target-template selects", async () => {
    renderApp();

    expect(await screen.findByRole("combobox", { name: "选择游戏" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "选择代理人" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "选择目标模板" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "创建目标模板" })).toBeEnabled();
  });

  it("keeps the same global inventory when switching agents", async () => {
    const user = userEvent.setup();
    renderApp();
    await user.click(await screen.findByRole("tab", { name: /全局库存/ }));
    expect(await screen.findByText("inv_demo_001")).toBeVisible();
    expect(screen.getByText("inv_demo_003")).toBeVisible();

    const agentSelect = screen.getByRole("combobox", { name: "选择代理人" });
    fireEvent.mouseDown(agentSelect);
    const option = await screen.findByText("星徽·比利", { selector: ".ant-select-item-option-content div" });
    await user.click(option);

    await waitFor(() => expect(screen.getByText("星徽·比利", { selector: ".agent-strip strong" })).toBeVisible());
    expect(screen.getByText("inv_demo_001")).toBeVisible();
    expect(screen.getByText("inv_demo_003")).toBeVisible();
    expect(screen.getByTitle("内置 · 星徽·比利目标")).toBeVisible();
  });

  it("equips an inventory item without removing it from the global list", async () => {
    const user = userEvent.setup();
    renderApp();
    await user.click(await screen.findByRole("tab", { name: /全局库存/ }));
    const row = (await screen.findByText("inv_demo_001")).closest("tr");
    expect(row).not.toBeNull();
    await user.click(within(row!).getByRole("button", { name: "装备 inv_demo_001" }));
    await waitFor(() => {
      const updatedRow = screen
        .getAllByText("inv_demo_001")
        .map((element) => element.closest("tr"))
        .find((element) => element !== null);
      expect(updatedRow).toHaveTextContent("叶瞬光");
    });

    await user.click(screen.getByRole("tab", { name: "当前装备" }));
    expect(
      screen
        .getAllByText("inv_demo_001")
        .some((element) => element.closest(".loadout-slot") !== null),
    ).toBe(true);
  });
});
