"""Render the actual update-page construction with host LVGL and device fonts."""
from pathlib import Path
import argparse
import shutil
import tempfile
import subprocess


ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--board-dir', type=Path, default=ROOT / 'xiaozhi-firmware/main/boards/round-voice-175c')
parser.add_argument('--lvgl-dir', type=Path, default=ROOT / 'xiaozhi-firmware/managed_components/lvgl__lvgl')
parser.add_argument('--build-dir', type=Path, required=True, help='Configured host warm-render CMake build')
parser.add_argument('--output-dir', type=Path, default=ROOT / 'artifacts/update-preview')
parser.add_argument('--cmake', default=shutil.which('cmake') or 'cmake')
parser.add_argument('--cxx', default=shutil.which('g++') or 'g++')
args = parser.parse_args()
from PIL import Image
BOARD, LVGL, BUILD = args.board_dir.resolve(), args.lvgl_dir.resolve(), args.build_dir.resolve()
OUT = args.output_dir.resolve()
# All generated compiler inputs live in an ignored output directory.
SCRATCH = OUT / 'build-inputs'
OUT.mkdir(parents=True, exist_ok=True)
SCRATCH.mkdir(parents=True, exist_ok=True)
(SCRATCH / 'lv_conf.h').write_bytes((ROOT / 'tests/warm-render/lv_conf.h').read_bytes())
source = (BOARD / 'round_display.cc').read_text('utf-8')
body = source.split('void RoundVoiceDisplay::BuildUpdateUi() {', 1)[1].split(
    '\nvoid RoundVoiceDisplay::BindUpdate', 1)[0].rsplit('}', 1)[0]
assert '系统更新' in body and 'update_notes_' in body
program = r'''
#include "warm_ui.h"
#include "warm_assets.h"
#include <cassert>
#include <cstdio>
#include <vector>
static std::vector<uint16_t> pixels(466 * 466);
static void noop(lv_event_t*) {}
static void flush(lv_display_t* d, const lv_area_t* a, uint8_t* raw) {
    auto p = reinterpret_cast<uint16_t*>(raw);
    for (int y = a->y1; y <= a->y2; ++y)
        for (int x = a->x1; x <= a->x2; ++x) pixels[y * 466 + x] = *p++;
    lv_display_flush_ready(d);
}
struct Preview {
    enum { Options = 2, UpdatePage = 7 };
    lv_obj_t* pages_[8]{};
    lv_obj_t *update_current_, *update_new_, *update_status_, *update_notes_;
    lv_obj_t *update_progress_, *update_action_, *update_cancel_;
    static void OnUpdatePage(lv_event_t*) {}
    static void OnBack(lv_event_t*) {}
    static void OnUpdateAction(lv_event_t*) {}
    static void OnUpdateCancel(lv_event_t*) {}
    void RenderUpdate() {
        warm::SetText(update_current_, "当前版本 · 2.5.6");
        warm::SetText(update_new_, "在线更新");
        warm::SetText(update_status_, "已是最新版本");
        warm::SetText(update_notes_, "系统更新\n查看版本说明后安装");
        lv_obj_add_flag(update_progress_, LV_OBJ_FLAG_HIDDEN);
    }
    void BuildUpdateUi() {
''' + body + r'''
    }
};
static void save(lv_display_t* display, const char* path) {
    lv_obj_update_layout(lv_screen_active());
    lv_obj_invalidate(lv_screen_active());
    lv_refr_now(display);
    auto f = fopen(path, "wb");
    assert(f);
    fwrite(pixels.data(), 2, pixels.size(), f);
    fclose(f);
}
int main() {
    lv_init();
    auto display = lv_display_create(466, 466);
    static uint16_t buffer[466 * 32];
    lv_display_set_buffers(display, buffer, nullptr, sizeof(buffer), LV_DISPLAY_RENDER_MODE_PARTIAL);
    lv_display_set_flush_cb(display, flush);
    warm::Ui ui;
    warm::Callbacks cb{noop, noop, noop, noop, noop, noop, noop, noop, noop, noop, noop, nullptr};
    warm::Build(ui, cb);
    Preview p;
    p.pages_[2] = ui.pages[2];
    p.BuildUpdateUi();
    lv_label_set_text(ui.wifi_summary, "已连接");
    lv_label_set_text(ui.volume_value, "55%");
    lv_label_set_text(ui.brightness_value, "85%");
    lv_slider_set_value(ui.volume, 55, LV_ANIM_OFF);
    lv_slider_set_value(ui.brightness, 85, LV_ANIM_OFF);
    for (auto page : ui.pages) if (page) lv_obj_add_flag(page, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(p.pages_[7], LV_OBJ_FLAG_HIDDEN);
    lv_obj_remove_flag(ui.pages[2], LV_OBJ_FLAG_HIDDEN);
    save(display, "settings.rgb565");
    lv_obj_add_flag(ui.pages[2], LV_OBJ_FLAG_HIDDEN);
    lv_obj_remove_flag(p.pages_[7], LV_OBJ_FLAG_HIDDEN);
    save(display, "update.rgb565");
    warm::SetText(p.update_status_, "固件校验完成，重启后生效");
    save(display, "update-long-status.rgb565");
    puts("Rendered settings/update with actual construction and device fonts.");
}
'''
(SCRATCH / 'preview.cpp').write_text(program, encoding='utf-8')
subprocess.run([args.cmake,
                '--build', str(BUILD), '--target', 'warm_render', '-j', '4'], check=True)
objects = sorted(p for p in (BUILD / 'CMakeFiles/warm_render.dir').rglob('warm*.cc.*') if p.suffix in {'.obj', '.o'})
assert len(objects) >= 14
executable = SCRATCH / 'preview.exe'
subprocess.run([args.cxx, '-std=c++20', '-O2',
                '-DLV_CONF_INCLUDE_SIMPLE', '-DLV_KCONFIG_IGNORE',
                '-I' + str(SCRATCH), '-I' + str(BOARD), '-I' + str(LVGL),
                str(SCRATCH / 'preview.cpp'), *map(str, objects),
                str(BUILD / 'lvgl/lib/liblvgl.a'), '-o', str(executable)], check=True)
subprocess.run([str(executable)], cwd=OUT, check=True)
for path in OUT.glob('*.rgb565'):
    raw = path.read_bytes()
    rgb = bytearray()
    for offset in range(0, len(raw), 2):
        value = raw[offset] | raw[offset + 1] << 8
        rgb.extend(((value >> 11) * 255 // 31, ((value >> 5) & 63) * 255 // 63,
                    (value & 31) * 255 // 31))
    Image.frombytes('RGB', (466, 466), bytes(rgb)).save(path.with_suffix('.png'))
print('Preview PNGs saved in', OUT)
