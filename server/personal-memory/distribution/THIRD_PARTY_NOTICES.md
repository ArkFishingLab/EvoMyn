# Third-party notices

The root MIT license covers this project's own additions. Upstream files retain their original notices.

| Component | Source | License / distribution |
| --- | --- | --- |
| Mnemosyne SDK | AxDSan/mnemosyne, `mnemosyne-memory` 3.15.1 | MIT; installed from Python requirements, not vendored |
| Dashboard adaptation | wysie/mnemosyne-dashboard, commit `ea3fda256fcd5deef8b91691daff52195005f5f0` | MIT; retained `viewer/LICENSE`, `viewer/SOURCE.json` |
| Xiaozhi firmware, when included | 78/xiaozhi-esp32, upstream basis 2.5.2 | MIT; retained `firmware/LICENSE` and source notices |
| World time adapter | modelcontextprotocol/servers, time provider | MIT; optional pinned installation from PyPI, not bundled |
| Python dependencies | MCP SDK, websockets, python-dotenv, filelock, fastembed, ONNX Runtime, cryptography and their dependencies | Installed separately; their own package licenses apply |
| Semantic model | sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 | Downloaded separately by the embedding backend; model's own terms apply |

No Microsoft YaHei, Bahnschrift, their generated glyph subsets, private runtime webfonts or proprietary firmware images are distributed.
The PC dashboard uses locally available system fonts. Optional firmware font generation requires a font supplied with appropriate use and redistribution rights; retain its license when distributing generated assets.

Source attribution is not an endorsement by upstream maintainers. Please preserve original copyright and license files in redistributions.
