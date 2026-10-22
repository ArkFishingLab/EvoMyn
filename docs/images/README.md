# README 图片与来源

- `memory-workflow.svg`：为项目手工绘制的可编辑矢量示意图，展示 ESP 语音入口、小智云端、PC 本地 MCP 与记忆库、多个 AI 客户端之间的关系。不是产品界面截图；不包含真实记忆或配置，字体使用系统回退，不附带字体文件。
- `desktop-connections.png`：Windows 桌面版「客户端接入」，展示本机配置导出、可选小智连接及 MCP 总开关。
- `capability-market.png`：看板「能力商城」，展示已适配的记忆档案与世界时间。

以上桌面截图来自 EvoMyn 0.2.9 打包应用的隔离验收环境，未修改产品界面，不包含正式数据库、个人记忆或真实接入点。

- `esp-device-home.png`：项目原生 LVGL 首页渲染，展示时钟、语音入口、待办日程与设置。使用演示状态，非实物摄影。
- `esp-device-voice.png`：项目原生 LVGL 语音页渲染，展示聆听状态。使用演示状态，非实物摄影。
- `esp-device-concept.png`：通过内置 imagegen 生成的硬件外观概念图。输入为用户提供的白色圆形设备外观参考和项目原生首页渲染；不代表实物照片、生产规格或对其他 ESP 板型的兼容承诺。

图片介绍当前主分支；已发布安装包以对应 Release 为准。更新截图时应继续使用隔离数据，勿截取用户的正式资料或凭证。

## 概念图生成提示词

使用内置 imagegen 工具，提示词如下；图片 1 为用户提供的外观参考，图片 2 为 `esp-device-home.png` 对应的原生渲染。

> Use case: product-mockup. Asset type: landscape hardware showcase image for the open-source EvoMyn README. Generate one premium, restrained studio product concept render based on the two supplied references. Image 1 is a tiny physical form reference: a compact circular black screen surrounded by a smooth ivory white enclosure, standing upright on a discreet white oval desktop foot, with a fine white USB cable trailing naturally behind it. Preserve this basic circular shape and desktop footprint; do not invent extra buttons, cameras, or sensors. Image 2 is the project's actual native 466x466 screen render, serving as the screen-content reference: dark warm charcoal background, quiet olive secondary text, the time 18:44, a muted amber circular voice waveform button, and two small bottom controls. Place a faithful version of this supplied home interface on the circular screen, respecting the circular safe area. All screen content must remain inside the display; don't create a square screen or clip text. Frame a single device in an almost frontal very slight three-quarter view on a seamless pale warm-gray tabletop, elegant diffuse daylight from upper left, fine realistic plastic edge and glass reflections, soft contact shadow, a very subtle curved cable. The device is the focus and fills much of the composition with generous surrounding whitespace. 3:2 landscape composition, crisp high-resolution hardware rendering. No laptop, no phone, no plants, no people, no logos or promotional text outside the screen, no watermark, no exaggerated neon or sci-fi effects. This will be explicitly captioned as a hardware concept illustration, not represented as a real photograph or a manufacturing specification.
