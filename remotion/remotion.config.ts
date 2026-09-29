import { Config } from "@remotion/cli/config";

Config.setPublicDir("./public");

Config.overrideWebpackConfig((currentConfig) => {
  return currentConfig;
});
Config.setDefaultCodingAgent('claude-code');
