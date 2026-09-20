/**
 * 七牛云 Kodo：读配置、生成上传凭证、上传本地文件。
 */

import qiniu from "qiniu";

export type QiniuConfig = {
  accessKey: string;
  secretKey: string;
  bucket: string;
  /** 公开访问域名，如 https://cdn.example.com（可无末尾 /） */
  domain: string;
  /** 对象 key 前缀，默认 webppt/ */
  keyPrefix: string;
  /** 机房 id：z0|z1|z2|na0|as0|cn-east-2；空则 SDK 自动探测 */
  region: string;
};

export function getQiniuConfig(): QiniuConfig | null {
  const accessKey = (process.env.QINIU_ACCESS_KEY || "").trim();
  const secretKey = (process.env.QINIU_SECRET_KEY || "").trim();
  const bucket = (process.env.QINIU_BUCKET || "").trim();
  const domain = (process.env.QINIU_DOMAIN || "").trim().replace(/\/+$/, "");
  if (!accessKey || !secretKey || !bucket || !domain) {
    return null;
  }
  const keyPrefix = (process.env.QINIU_KEY_PREFIX || "webppt/").trim();
  const region = (process.env.QINIU_REGION || "").trim();
  return {
    accessKey,
    secretKey,
    bucket,
    domain,
    keyPrefix: keyPrefix.endsWith("/") ? keyPrefix : `${keyPrefix}/`,
    region,
  };
}

export function qiniuPublicUrl(cfg: QiniuConfig, key: string): string {
  const k = key.replace(/^\/+/, "");
  return `${cfg.domain}/${k}`;
}

function buildConfig(cfg: QiniuConfig): qiniu.conf.Config {
  const options: qiniu.conf.ConfigOptions = {
    useHttpsDomain: true,
  };
  if (cfg.region) {
    options.regionsProvider = qiniu.httpc.Region.fromRegionId(cfg.region);
  }
  return new qiniu.conf.Config(options);
}

export function makeUploadToken(
  cfg: QiniuConfig,
  key: string,
  expiresSec = 3600,
): string {
  const mac = new qiniu.auth.digest.Mac(cfg.accessKey, cfg.secretKey);
  const putPolicy = new qiniu.rs.PutPolicy({
    scope: `${cfg.bucket}:${key}`,
    expires: expiresSec,
  });
  return putPolicy.uploadToken(mac);
}

export async function uploadFileToQiniu(opts: {
  localPath: string;
  key: string;
  cfg?: QiniuConfig | null;
}): Promise<{ key: string; url: string; hash?: string; fsize?: number }> {
  const cfg = opts.cfg ?? getQiniuConfig();
  if (!cfg) {
    throw new Error(
      "未配置七牛云。请在 .env.local 设置 QINIU_ACCESS_KEY / QINIU_SECRET_KEY / QINIU_BUCKET / QINIU_DOMAIN",
    );
  }

  const key = opts.key.replace(/^\/+/, "");
  const token = makeUploadToken(cfg, key);
  const config = buildConfig(cfg);
  const formUploader = new qiniu.form_up.FormUploader(config);
  const putExtra = new qiniu.form_up.PutExtra();

  const result = await formUploader.putFile(
    token,
    key,
    opts.localPath,
    putExtra,
  );

  const wrapper = result as {
    data?: { key?: string; hash?: string; fsize?: number };
    resp?: { statusCode?: number };
    ok?: () => boolean;
  };
  const ok =
    typeof wrapper.ok === "function"
      ? wrapper.ok()
      : wrapper.resp?.statusCode === 200;
  if (!ok) {
    throw new Error(
      `七牛上传失败 HTTP ${wrapper.resp?.statusCode ?? "?"}: ${JSON.stringify(wrapper.data ?? result)}`,
    );
  }

  const body = wrapper.data || {};
  return {
    key: body.key || key,
    url: qiniuPublicUrl(cfg, body.key || key),
    hash: body.hash,
    fsize: typeof body.fsize === "number" ? body.fsize : undefined,
  };
}
