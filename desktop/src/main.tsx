import React from "react";
import ReactDOM from "react-dom/client";
import { App as AntApp, ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";

import App from "./App";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: "#087f78",
          colorInfo: "#2563a6",
          colorSuccess: "#27834a",
          colorWarning: "#b76b00",
          colorError: "#bd3030",
          borderRadius: 6,
          fontFamily:
            '"Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei", sans-serif',
        },
        components: {
          Table: { headerBg: "#eef2f4", headerColor: "#25343d" },
          Tabs: { itemSelectedColor: "#087f78", inkBarColor: "#087f78" },
        },
      }}
    >
      <AntApp>
        <App />
      </AntApp>
    </ConfigProvider>
  </React.StrictMode>,
);
