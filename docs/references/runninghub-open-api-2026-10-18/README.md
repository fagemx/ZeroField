# RunningHub RH STORY Open API snapshot

Captured on 2026-10-18 (Asia/Taipei) from the official [Open API documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api).

- OpenAPI: 3.0.3; API version: v1
- Operations: **98**; URL paths: **75**; functional groups: **15**
- Methods: GET 36, POST 33, DELETE 11, PATCH 8, PUT 10
- Original specification: 473,197 bytes; SHA-256: `084e31ae6f20a0ca62a9942efcfb4b466444289d34797a4c0c2b29da0e4f4c37`
- Downloaded server URL: `https://story.runninghub.ai/aivideo/open/v1`

## Files

- [openapi.json](openapi.json): official downloaded specification, preserved byte for byte.
- [API_REFERENCE.md](API_REFERENCE.md): complete operation specifications organized by functional group.
- [endpoints.json](endpoints.json): searchable index with parameters, content types, response codes, and source links.
- [web-pages/](web-pages/): rendered documentation text for every endpoint, including the selected code-example tab.
- [endpoint-sources.json](endpoint-sources.json): source URL and capture timestamp for every endpoint.
- [guides/](guides/): introductory examples in cURL, Python, JavaScript and Java; conventions; error codes; Webhook guide.
- [source-pages.json](source-pages.json): source metadata for the supplementary guides.
- [manifest.json](manifest.json): file hashes, operation counts, and integrity checks.

## Capture scope

This is a documentation snapshot. No account API key, account console contents, private project data, generation task, or live API result is included. API functionality was not exercised.

The introductory guide lists regional www.runninghub.cn / www.runninghub.ai base URLs, while the downloaded specification declares story.runninghub.ai. Both original sources are retained without reconciling that difference.

Web text captures the code tab selected when each endpoint was read. All schemas and examples present in the official JSON are retained in openapi.json and API_REFERENCE.md.

## Supplementary guides

- [开始使用 / cURL](guides/01-getting-started-curl.txt) - [official page](https://story.runninghub.ai/zh-cn/ai-comic/open-api)
- [开始使用 / Python](guides/01-getting-started-python.txt) - [official page](https://story.runninghub.ai/zh-cn/ai-comic/open-api)
- [开始使用 / JavaScript](guides/01-getting-started-javascript.txt) - [official page](https://story.runninghub.ai/zh-cn/ai-comic/open-api)
- [开始使用 / Java](guides/01-getting-started-java.txt) - [official page](https://story.runninghub.ai/zh-cn/ai-comic/open-api)
- [统一约定](guides/02-conventions.txt) - [official page](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=conventions)
- [错误码](guides/03-error-codes.txt) - [official page](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=error-codes)
- [Webhook](guides/19-webhook.txt) - [official page](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=webhook)

## Endpoint index

| Group | Operations |
| --- | ---: |
| 目录 | 5 |
| 文件 | 3 |
| 一键导入 | 2 |
| 剧本 | 5 |
| 自定义画风 | 4 |
| 项目 | 6 |
| 剧集与剧本 | 7 |
| 资产 | 19 |
| 分场与分镜 | 11 |
| 镜头产出 | 15 |
| 成片与文件 | 3 |
| 任务 | 3 |
| 平台 | 7 |
| 计费 | 2 |
| Webhook 管理 | 6 |

### 目录

| Method | Path | Function | Reference |
| --- | --- | --- | --- |
| GET | `/capabilities` | 能力清单 | [details](API_REFERENCE.md#get-capabilities) |
| GET | `/catalog/apps` | 应用目录 | [details](API_REFERENCE.md#get-catalog-apps) |
| GET | `/catalog/styles` | 画风目录 | [details](API_REFERENCE.md#get-catalog-styles) |
| GET | `/catalog/director-styles` | 导演风格目录 | [details](API_REFERENCE.md#get-catalog-director-styles) |
| GET | `/catalog/aspect-ratios` | 画幅比例目录 | [details](API_REFERENCE.md#get-catalog-aspect-ratios) |

### 文件

| Method | Path | Function | Reference |
| --- | --- | --- | --- |
| POST | `/files` | 上传文件 | [details](API_REFERENCE.md#upload-file) |
| GET | `/files/{fileId}` | 查询文件 | [details](API_REFERENCE.md#get-file) |
| DELETE | `/files/{fileId}` | 删除文件 | [details](API_REFERENCE.md#delete-file) |

### 一键导入

| Method | Path | Function | Reference |
| --- | --- | --- | --- |
| POST | `/project-imports` | 导入剧本建项目 | [details](API_REFERENCE.md#import-project) |
| POST | `/project-generations` | AI 创意生成项目 | [details](API_REFERENCE.md#generate-project) |

### 剧本

| Method | Path | Function | Reference |
| --- | --- | --- | --- |
| POST | `/episodes/{episodeId}/script-refinements` | AI 润色剧本 | [details](API_REFERENCE.md#refine-script) |
| GET | `/episodes/{episodeId}/script/versions` | 剧本快照列表 | [details](API_REFERENCE.md#list-script-versions) |
| GET | `/episodes/{episodeId}/script/versions/{versionId}` | 剧本快照详情 | [details](API_REFERENCE.md#get-script-version) |
| POST | `/script-detections` | 检测内容类型 | [details](API_REFERENCE.md#detect-script-type) |
| POST | `/projects/{projectId}/asset-reextractions` | 项目级重新提取资产 | [details](API_REFERENCE.md#reextract-project-assets) |

### 自定义画风

| Method | Path | Function | Reference |
| --- | --- | --- | --- |
| GET | `/styles/custom` | 自定义画风列表 | [details](API_REFERENCE.md#list-custom-styles) |
| POST | `/styles/custom` | 创建自定义画风 | [details](API_REFERENCE.md#create-custom-style) |
| PATCH | `/styles/custom/{styleId}` | 更新自定义画风 | [details](API_REFERENCE.md#update-custom-style) |
| DELETE | `/styles/custom/{styleId}` | 删除自定义画风 | [details](API_REFERENCE.md#delete-custom-style) |

### 项目

| Method | Path | Function | Reference |
| --- | --- | --- | --- |
| POST | `/projects` | 创建项目 | [details](API_REFERENCE.md#create-project) |
| GET | `/projects` | 项目列表 | [details](API_REFERENCE.md#list-projects) |
| GET | `/projects/{projectId}` | 查询项目 | [details](API_REFERENCE.md#get-project) |
| PATCH | `/projects/{projectId}` | 更新项目 | [details](API_REFERENCE.md#update-project) |
| DELETE | `/projects/{projectId}` | 删除项目 | [details](API_REFERENCE.md#delete-project) |
| GET | `/projects/{projectId}/episodes` | 项目剧集列表 | [details](API_REFERENCE.md#list-project-episodes) |

### 剧集与剧本

| Method | Path | Function | Reference |
| --- | --- | --- | --- |
| POST | `/projects/{projectId}/episodes` | 创建剧集 | [details](API_REFERENCE.md#create-episode) |
| GET | `/episodes/{episodeId}` | 查询剧集 | [details](API_REFERENCE.md#get-episode) |
| PATCH | `/episodes/{episodeId}` | 更新剧集 | [details](API_REFERENCE.md#update-episode) |
| DELETE | `/episodes/{episodeId}` | 删除剧集 | [details](API_REFERENCE.md#delete-episode) |
| PUT | `/episodes/{episodeId}/script` | 更新剧本 | [details](API_REFERENCE.md#update-script) |
| GET | `/episodes/{episodeId}/settings` | 查询剧集设置 | [details](API_REFERENCE.md#get-episode-settings) |
| PUT | `/episodes/{episodeId}/settings` | 更新剧集设置 | [details](API_REFERENCE.md#update-episode-settings) |

### 资产

| Method | Path | Function | Reference |
| --- | --- | --- | --- |
| POST | `/episodes/{episodeId}/asset-extractions` | 提取资产 | [details](API_REFERENCE.md#extract-assets) |
| GET | `/episodes/{episodeId}/assets` | 资产列表 | [details](API_REFERENCE.md#list-assets) |
| POST | `/episodes/{episodeId}/assets` | 创建资产 | [details](API_REFERENCE.md#create-asset) |
| POST | `/assets/{assetId}/image-generations` | 资产生图 | [details](API_REFERENCE.md#generate-asset-image) |
| GET | `/assets/{assetId}` | 查询资产详情 | [details](API_REFERENCE.md#get-asset-detail) |
| PATCH | `/assets/{assetId}` | 更新资产 | [details](API_REFERENCE.md#update-asset) |
| DELETE | `/assets/{assetId}` | 删除资产 | [details](API_REFERENCE.md#delete-asset) |
| POST | `/assets/{assetId}/images` | 上传资产形象图 | [details](API_REFERENCE.md#upload-asset-image) |
| GET | `/assets/{assetId}/images` | 资产图片历史 | [details](API_REFERENCE.md#list-asset-images) |
| POST | `/assets/{assetId}/image-edits` | AI 改图 | [details](API_REFERENCE.md#edit-asset-image) |
| PUT | `/assets/{assetId}/selected-image` | 选中资产图片 | [details](API_REFERENCE.md#select-asset-image) |
| DELETE | `/assets/{assetId}/images/{imageId}` | 删除资产图片 | [details](API_REFERENCE.md#delete-asset-image) |
| GET | `/assets/{assetId}/variants` | 变体列表 | [details](API_REFERENCE.md#list-asset-variants) |
| POST | `/assets/{assetId}/variants` | 创建变体 | [details](API_REFERENCE.md#create-asset-variant) |
| PATCH | `/assets/{assetId}/variants/{variantId}` | 更新变体 | [details](API_REFERENCE.md#update-asset-variant) |
| DELETE | `/assets/{assetId}/variants/{variantId}` | 删除变体 | [details](API_REFERENCE.md#delete-asset-variant) |
| PUT | `/assets/{assetId}/style` | 绑定资产画风 | [details](API_REFERENCE.md#update-asset-style) |
| PUT | `/assets/{assetId}/scenes` | 设置资产出场场次 | [details](API_REFERENCE.md#update-asset-scenes) |
| PUT | `/shots/{shotId}/assets` | 设置镜头绑定资产 | [details](API_REFERENCE.md#update-shot-assets) |

### 分场与分镜

| Method | Path | Function | Reference |
| --- | --- | --- | --- |
| GET | `/episodes/{episodeId}/scenes` | 场次列表 | [details](API_REFERENCE.md#list-scenes) |
| POST | `/episodes/{episodeId}/scenes` | 创建场次 | [details](API_REFERENCE.md#create-scene) |
| GET | `/scenes/{sceneId}` | 查询场次详情 | [details](API_REFERENCE.md#get-scene-detail) |
| PATCH | `/scenes/{sceneId}` | 更新场次 | [details](API_REFERENCE.md#update-scene) |
| DELETE | `/scenes/{sceneId}` | 删除场次 | [details](API_REFERENCE.md#delete-scene) |
| PUT | `/episodes/{episodeId}/scene-order` | 场次重新排序 | [details](API_REFERENCE.md#reorder-scenes) |
| POST | `/scene-merges` | 合并场次 | [details](API_REFERENCE.md#merge-scenes) |
| POST | `/scenes/{sceneId}/refinements` | AI 改写场次 | [details](API_REFERENCE.md#refine-scene) |
| POST | `/episodes/{episodeId}/storyboards` | 整集生成分镜 | [details](API_REFERENCE.md#generate-storyboard) |
| POST | `/scenes/{sceneId}/shot-rebuilds` | 单场重建分镜 | [details](API_REFERENCE.md#rebuild-shots) |
| GET | `/episodes/{episodeId}/shots` | 镜头列表 | [details](API_REFERENCE.md#list-shots-by-episode) |

### 镜头产出

| Method | Path | Function | Reference |
| --- | --- | --- | --- |
| POST | `/shots/{shotId}/image-generations` | 镜头生图 | [details](API_REFERENCE.md#generate-shot-image) |
| POST | `/shots/{shotId}/video-generations` | 镜头生视频 | [details](API_REFERENCE.md#generate-shot-video) |
| PUT | `/shots/{shotId}/selected-image` | 选定镜头图 | [details](API_REFERENCE.md#select-shot-image) |
| PUT | `/shots/{shotId}/selected-video` | 选定镜头视频 | [details](API_REFERENCE.md#select-shot-video) |
| GET | `/shots/{shotId}/images` | 镜头图列表 | [details](API_REFERENCE.md#list-shot-images) |
| GET | `/shots/{shotId}/videos` | 镜头视频列表 | [details](API_REFERENCE.md#list-shot-videos) |
| GET | `/shots/{shotId}` | 查询镜头详情 | [details](API_REFERENCE.md#get-shot) |
| PATCH | `/shots/{shotId}` | 更新镜头 | [details](API_REFERENCE.md#patch-shot) |
| DELETE | `/shots/{shotId}` | 删除镜头 | [details](API_REFERENCE.md#delete-shot) |
| POST | `/scenes/{sceneId}/shots` | 创建镜头 | [details](API_REFERENCE.md#create-shot) |
| POST | `/shots/{shotId}/splits` | 拆分镜头 | [details](API_REFERENCE.md#split-shot) |
| POST | `/shot-merges` | 合并镜头 | [details](API_REFERENCE.md#merge-shots) |
| PUT | `/shots/{shotId}/position` | 移动镜头 | [details](API_REFERENCE.md#move-shot) |
| PATCH | `/shots` | 批量更新镜头 | [details](API_REFERENCE.md#batch-update-shots) |
| DELETE | `/shots/{shotId}/narrative-edits` | 重置镜头叙事 | [details](API_REFERENCE.md#reset-shot-narrative) |

### 成片与文件

| Method | Path | Function | Reference |
| --- | --- | --- | --- |
| POST | `/episodes/{episodeId}/films` | 导出成片 | [details](API_REFERENCE.md#export-film) |
| GET | `/episodes/{episodeId}/films` | 成片列表 | [details](API_REFERENCE.md#list-films) |
| GET | `/files/{fileId}/url` | 重新获取文件地址 | [details](API_REFERENCE.md#get-file-url) |

### 任务

| Method | Path | Function | Reference |
| --- | --- | --- | --- |
| GET | `/tasks/{taskNo}` | 查询任务 | [details](API_REFERENCE.md#get-task) |
| GET | `/tasks` | 任务列表 | [details](API_REFERENCE.md#list-tasks) |
| POST | `/tasks/{taskNo}/cancellations` | 取消任务 | [details](API_REFERENCE.md#cancel-task) |

### 平台

| Method | Path | Function | Reference |
| --- | --- | --- | --- |
| POST | `/tasks/{taskNo}/retries` | 重试任务 | [details](API_REFERENCE.md#retry-task) |
| POST | `/episodes/{episodeId}/shot-image-generations` | 批量镜头生图 | [details](API_REFERENCE.md#batch-generate-shot-images) |
| POST | `/episodes/{episodeId}/shot-video-generations` | 批量镜头生视频 | [details](API_REFERENCE.md#batch-generate-shot-videos) |
| GET | `/task-groups/{groupId}` | 查询批次任务组 | [details](API_REFERENCE.md#get-task-group) |
| GET | `/usage` | 用量查询 | [details](API_REFERENCE.md#get-usage) |
| GET | `/balance` | 余额查询 | [details](API_REFERENCE.md#get-balance) |
| GET | `/quota` | 配额查询 | [details](API_REFERENCE.md#get-quota) |

### 计费

| Method | Path | Function | Reference |
| --- | --- | --- | --- |
| GET | `/bills` | 账单列表 | [details](API_REFERENCE.md#list-bills) |
| GET | `/bills/{billNo}` | 查询账单 | [details](API_REFERENCE.md#get-bill) |

### Webhook 管理

| Method | Path | Function | Reference |
| --- | --- | --- | --- |
| POST | `/webhooks` | 登记回调地址 | [details](API_REFERENCE.md#create-webhook) |
| GET | `/webhooks` | 回调地址列表 | [details](API_REFERENCE.md#list-webhooks) |
| DELETE | `/webhooks/{webhookId}` | 删除回调地址 | [details](API_REFERENCE.md#delete-webhook) |
| POST | `/webhooks/{webhookId}/test-deliveries` | 发送测试事件 | [details](API_REFERENCE.md#test-webhook) |
| GET | `/webhooks/{webhookId}/deliveries` | 投递记录列表 | [details](API_REFERENCE.md#list-webhook-deliveries) |
| POST | `/webhooks/{webhookId}/deliveries/{deliveryId}/redeliveries` | 手动重投 | [details](API_REFERENCE.md#redeliver-webhook-delivery) |
