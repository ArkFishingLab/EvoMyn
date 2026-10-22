# 圆屏网页预览

`index.html`、`app.mjs`、`round-layout.mjs` 和 `settings-model.mjs` 展示 466 × 466 圆屏交互与布局。预览使用浏览器模拟状态，不连接真实设备，也不证明固件显示或音频已验收。

从仓库根目录启动静态服务，再打开 `http://127.0.0.1:18766/`：

```powershell
python -m http.server 18766 --bind 127.0.0.1 --directory preview
```

生成可直接打开的单 HTML 预览：

```powershell
python preview/build_standalone.py
```

输出为 `中文圆屏预览.html`。修改源模块后重新生成，不直接维护拼接后的页面。

```powershell
node --test tests/preview-settings.test.mjs tests/round-layout.test.mjs
```

原生 LVGL 渲染及硬件检查见[开发指南](../docs/development.md)。
