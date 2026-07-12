import { Config } from "@remotion/cli/config";

// 出力設定。JPEG フレームで高速化、既存ファイルは上書き。
Config.setVideoImageFormat("jpeg");
Config.setOverwriteOutput(true);
