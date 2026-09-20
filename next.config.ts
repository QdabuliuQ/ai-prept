import type { NextConfig } from "next";
import path from "path";
import type { RuleSetRule, RuleSetUseItem } from "webpack";

function isRegexRule(rule: RuleSetRule): rule is RuleSetRule & { test: RegExp } {
  return rule.test instanceof RegExp;
}

function withLessLoader(use: RuleSetUseItem | RuleSetUseItem[]): RuleSetUseItem[] {
  const loaders = Array.isArray(use) ? [...use] : [use];

  const nextLoaders = loaders.map((loader) => {
    if (
      typeof loader === "object" &&
      loader !== null &&
      "loader" in loader &&
      String(loader.loader).includes("css-loader")
    ) {
      const options =
        typeof loader.options === "object" && loader.options !== null
          ? loader.options
          : {};
      return {
        ...loader,
        options: {
          ...options,
          importLoaders:
            (typeof options === "object" &&
            options !== null &&
            "importLoaders" in options &&
            typeof options.importLoaders === "number"
              ? options.importLoaders
              : 1) + 1,
        },
      };
    }
    return loader;
  });

  nextLoaders.push({
    loader: "less-loader",
    options: {
      lessOptions: {
        javascriptEnabled: true,
      },
    },
  });

  return nextLoaders;
}

const nextConfig: NextConfig = {
  reactStrictMode: true,
  experimental: {
    reactCompiler: true,
  },
  serverExternalPackages: [
    "qiniu",
    "sharp",
    "archiver",
    "html-minifier-terser",
    "csso",
    "puppeteer",
  ],
  eslint: {
    // Keep build unblocked; run `npm run lint` separately
    ignoreDuringBuilds: true,
  },
  typescript: {
    // Typecheck still runs; set true only if blocking on legacy any issues
    ignoreBuildErrors: false,
  },
  transpilePackages: [
    "antd",
    "@ant-design/icons",
    "@ant-design/v5-patch-for-react-19",
    "@webppt/html-to-pptx",
  ],
  webpack: (config, { isServer, webpack }) => {
    // Package main points at src/ (imports .less); use prebuilt dist instead
    config.resolve = config.resolve ?? {};
    config.resolve.alias = {
      ...config.resolve.alias,
      "@webppt/html-to-pptx": path.resolve(
        __dirname,
        "packages/html-to-pptx/src/index.ts",
      ),
    };

    // pptxgenjs / similar packages import node: builtins; strip scheme + stub on client
    config.plugins = config.plugins ?? [];
    config.plugins.push(
      new webpack.NormalModuleReplacementPlugin(/^node:/, (resource: {
        request: string;
      }) => {
        resource.request = resource.request.replace(/^node:/, "");
      })
    );

    if (!isServer) {
      config.resolve.fallback = {
        ...config.resolve.fallback,
        fs: false,
        https: false,
        http: false,
        path: false,
        stream: false,
        crypto: false,
        net: false,
        tls: false,
        child_process: false,
      };
    }

    const oneOfRule = config.module?.rules?.find(
      (rule): rule is { oneOf: RuleSetRule[] } =>
        typeof rule === "object" &&
        rule !== null &&
        "oneOf" in rule &&
        Array.isArray((rule as { oneOf?: unknown }).oneOf)
    );

    if (!oneOfRule) {
      return config;
    }

    const cssModuleIndex = oneOfRule.oneOf.findIndex(
      (rule) =>
        isRegexRule(rule) &&
        rule.test.test("file.module.css") &&
        !rule.test.test("file.module.scss") &&
        !rule.test.test("file.css")
    );

    const globalCssIndex = oneOfRule.oneOf.findIndex(
      (rule) =>
        isRegexRule(rule) &&
        rule.test.test("file.css") &&
        !rule.test.test("file.module.css") &&
        !rule.test.test("file.scss")
    );

    if (cssModuleIndex !== -1) {
      const cssModuleRule = oneOfRule.oneOf[cssModuleIndex];
      oneOfRule.oneOf.splice(cssModuleIndex, 0, {
        ...cssModuleRule,
        test: /\.module\.less$/,
        use: withLessLoader(cssModuleRule.use as RuleSetUseItem),
      });
    }

    if (globalCssIndex !== -1) {
      // Indices may have shifted after previous splice
      const refreshedGlobalCssIndex = oneOfRule.oneOf.findIndex(
        (rule) =>
          isRegexRule(rule) &&
          rule.test.test("file.css") &&
          !rule.test.test("file.module.css") &&
          !rule.test.test("file.scss")
      );
      if (refreshedGlobalCssIndex !== -1) {
        const globalCssRule = oneOfRule.oneOf[refreshedGlobalCssIndex];
        oneOfRule.oneOf.splice(refreshedGlobalCssIndex, 0, {
          ...globalCssRule,
          test: /\.less$/,
          exclude: /\.module\.less$/,
          use: withLessLoader(globalCssRule.use as RuleSetUseItem),
        });
      }
    }

    return config;
  },
};

export default nextConfig;
