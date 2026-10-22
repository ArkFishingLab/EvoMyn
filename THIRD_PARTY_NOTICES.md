# Third-party notices

The root [MIT licence](LICENSE) covers this project's own additions. Upstream files retain their original copyright, licence and attribution. A dependency's licence is not replaced by the root licence.

| Component | Source basis | Licence / retained evidence |
| --- | --- | --- |
| Windows desktop shell | Electron 45.0.0 / Chromium | MIT and bundled Chromium third-party licences; retained in installed application |
| Desktop portable Python | CPython 3.11.14 | Python Software Foundation licence; bundled `resources/backend/python/LICENSE.txt` |
| Desktop Python dependency closure | Exact direct pins in `server/personal-memory/requirements.txt`; transitive versions in generated `RUNTIME-SOURCES.json` | Distribution licence texts retained in bundled `.dist-info` directories |
| Optional marketplace installer | Astral uv 0.10.7 | MIT OR Apache-2.0; retained [MIT](desktop/assets/licenses/uv-LICENSE-MIT), [Apache-2.0](desktop/assets/licenses/uv-LICENSE-APACHE) |
| Mnemosyne SDK | `AxDSan/mnemosyne`, `mnemosyne-memory==3.15.1` | MIT; installed separately from requirements |
| Archive viewer adaptation | `wysie/mnemosyne-dashboard`, commit `ea3fda256fcd5deef8b91691daff52195005f5f0` | MIT; [viewer/LICENSE](server/personal-memory/viewer/LICENSE), [viewer/SOURCE.json](server/personal-memory/viewer/SOURCE.json) |
| MCP WebSocket pipe | `78/mcp-calculator`, commit `c537f71d61fd73b47d6c8955b5df6d3721acf4e4` | MIT; adapted `server/personal-memory/vendor/mcp_pipe.py` |
| Xiaozhi firmware | `78/xiaozhi-esp32`, upstream source basis 2.5.2, with local changes | MIT; [xiaozhi-firmware/LICENSE](xiaozhi-firmware/LICENSE), source notices and component licences |
| Optional world time provider | `modelcontextprotocol/servers`, `mcp-server-time==2026.10.10` | MIT; installed on demand in a separate environment |
| Python dependencies | MCP SDK, websockets, python-dotenv, filelock, fastembed, ONNX Runtime, cryptography and transitive dependencies | Installed separately; package-specific licences apply |
| Semantic model | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | Downloaded separately by the embedding backend; retain the model publisher's terms |
| ESP-IDF and component registry dependencies | Versions and sources declared in firmware manifests | Resolved separately; retain each component's licence |
| GIF renderer | Firmware `main/display/lvgl_display/gif/` | Retained [component licence](xiaozhi-firmware/main/display/lvgl_display/gif/LICENSE.txt) |
| Offline host-test JSON parser | Unmodified cJSON 1.7.19 from local ESP-IDF component `espressif/cjson` 1.7.19~2 | MIT; [licence](tests/support/cjson/LICENSE) and [source/version/SHA-256 record](tests/support/cjson/SOURCE.json); used only by host tests |

Public source exports exclude Microsoft YaHei, Bahnschrift, generated subsets of those fonts, private runtime webfonts and private production images. The PC dashboard uses locally available system fonts. Public firmware 2.5.10 generates its twelve round UI fonts from Noto Sans SC under SIL OFL; its release includes font provenance, licence texts and SDK/component notices. Upstream Noto text/emoji assets and Material Symbols retain their own licences. ESP-SR and some Espressif audio libraries restrict use to Espressif products; the complete firmware is not licensed solely under this project's MIT licence. Optional source builds require licensed static fonts and their licence texts; retain generated provenance and licence files when redistributing those assets.

The local vendor demonstration archive and downloaded SDK/component caches are not maintained public source. Exported firmware retains upstream small system prompt audio as part of its source distribution. Attribution does not imply endorsement by upstream maintainers.
