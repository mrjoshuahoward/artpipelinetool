"""Built-in asset classes. Briefs can use these by name, override fields per asset,
or define their own classes. Platform facts here follow the skill's references
(skills/casual-mobile-art-director/references/pipeline-*.md); re-check them when
platforms change."""
from __future__ import annotations

from artpipeline.schema import AssetClass

IOS_SYSTEM_BGS = ["#F2F2F7", "#1C1C1E"]  # iOS light / dark system backgrounds

PRESETS: dict[str, AssetClass] = {
    # Flattened 1024 App Store icon: no alpha, judged on wallpapers and system backgrounds.
    "ios_app_icon_flat": AssetClass(
        format="png", master=(1024, 1024), alpha="forbidden",
        display_sizes=[180, 120, 60], review_backgrounds=[*IOS_SYSTEM_BGS, "#3A6EA5"],
    ),
    # One Icon Composer layer: transparent, crisp edges, no baked gloss.
    "ios_app_icon_layer": AssetClass(
        format="png", master=(1024, 1024), alpha="required",
        display_sizes=[180, 60], review_backgrounds=IOS_SYSTEM_BGS,
    ),
    # Game Center achievement art: opaque, shown on light and dark system backgrounds.
    "game_center_badge": AssetClass(
        format="png", master=(1024, 1024), alpha="forbidden",
        display_sizes=[256, 64], review_backgrounds=IOS_SYSTEM_BGS,
    ),
    # iPhone 6.9" portrait App Store screenshot.
    "store_screenshot": AssetClass(
        format="png", master=(1320, 2868), alpha="forbidden", display_sizes=[400],
    ),
    # Generic in-game raster sprite; set master and renditions per project.
    "sprite": AssetClass(
        format="png", master=(512, 512), alpha="required", display_sizes=[128, 64],
    ),
    # Vector UI icon in points; exported @1x/@2x/@3x.
    "ui_icon_svg": AssetClass(
        format="svg", master=(44, 44), alpha="required", display_sizes=[44, 24],
        renditions=[
            {"suffix": "@1x", "scale": 1}, {"suffix": "@2x", "scale": 2}, {"suffix": "@3x", "scale": 3},
        ],
    ),
    # Pixel art: nearest-neighbour only, never AI-upscaled.
    "pixel_sprite": AssetClass(
        format="png", master=(32, 32), alpha="required", pixel_art=True, display_sizes=[128, 64],
    ),
    "tile": AssetClass(format="png", master=(256, 256), alpha="any", display_sizes=[128, 64]),
    "key_art": AssetClass(format="png", master=(2048, 1152), alpha="forbidden", display_sizes=[640]),
}
