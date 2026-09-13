# 前端发布与回退

此目录只用于现有 `jiuyue.club` Nginx 主机的前端更新。服务器的预约后端、电脑后台、手机后台、数据库及证书继续沿用现有服务。

## 发布准备

1. 完成根 README 中的所有检查，再提交并推送 `main`。
2. 从干净提交运行 `python scripts/package_release.py --output /path/outside/repository/frontend.tar.gz`。记录输出的提交和 SHA-256，确认远程 `main` 为同一提交。
3. 通过现有受信任连接上传发布包和该提交中的 `deploy_update.py`。凭据只由现有登录机制提供，不写入仓库、静态目录、命令记录或发布包。
4. 在现有服务器以 root 执行 `python3 deploy_update.py --inspect`，核对站点、当前配置摘要、前端目录和现有后台接口状态。
5. 使用刚刚核对的值执行：

```sh
python3 deploy_update.py \
  --archive /path/to/frontend.tar.gz \
  --sha256 VERIFIED_ARCHIVE_SHA256 \
  --expected-config VERIFIED_NGINX_CONFIG_SHA256 \
  --expected-release VERIFIED_CURRENT_RELEASE_DIRECTORY
```

占位符必须替换成同次核查所得的真实值。本脚本针对 `20260911` 标记的原有前端路由执行一次迁移；如果新路由已经存在或配置变化，会在切换前拒绝执行。后续发布应在当前配置上重新审查，不重复使用这次迁移参数。

## 切换行为

脚本校验压缩包路径、文件集合、逐文件摘要、生产页面和预约脚本；创建独立版本目录，备份旧配置和旧前端链接；只增加三个新前台样式／脚本的精确路由。`/assets/` 其他路径仍由现有后端处理，原管理脚本不会被静态前端截获。

`/index.html` 的外部请求跳转到 `/` 并保留查询参数；首页内部的 `index.html` 解析继续正常返回页面。通过 Nginx 配置检查后，原子替换 `/srv/jiuyue-frontend` 链接。

切换后逐一验证所有静态文件和 10 个视频的范围请求，核对后台资源与切换前一致、私有接口匿名访问为 401。预约只发送空 JSON 检查 422 拒绝行为，避免创建有效预约数据。任何切换后检查失败都会尝试恢复旧目录链接和旧配置，并验证原服务。

## 回退

成功记录的 `backup` 目录包含 `before.json`、旧 Nginx 配置、旧链接目标及 `deployment-result.json`。旧版本目录完整保留。人工回退前先确认当前链接和配置仍属于本次发布；如果已有后续变更，应先检查差异。

核对后恢复旧链接和配置，执行 `nginx -t`，成功后 reload Nginx，再检查首页、两个后台入口、健康接口和私有接口的访问控制。不要删除旧目录来回退，也不要覆盖数据库或后端文件。

本地的安全单元测试可以在 Windows 运行。设置 `NGINX_BINARY` 为独立 Nginx 可执行文件路径，可额外运行真实 Nginx 路由测试；它只监听本机临时端口，不使用生产域名的服务器。
# 预约页微信二维码增量更新

`deploy_static_update.py` 用于从 2026-09-12 的已上线版本添加微信咨询区块。增量包包含 `booking/index.html`、`assets/production.css`、`assets/photos/wechat-contact.png` 与 `incremental-manifest.json`，其中记录来源仓库、基础提交、目标提交和三个文件的新旧 SHA-256。

先用 `--inspect` 核对服务器当前版本，再提供 `--archive`、`--sha256`、`--expected-config`、`--expected-release` 执行。程序完整校验基础版本，复制新目录、应用增量并原子切换前端链接；保留旧版本和回退记录。此次不修改 Nginx 配置，不写入预约数据。此程序针对“尚无该二维码”的基础版本，后续再次修改须明确新的增量范围与基础版本，不能重复套用旧命令。
