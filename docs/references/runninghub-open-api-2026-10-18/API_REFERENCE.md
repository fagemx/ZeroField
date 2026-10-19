# RH STORY Open API - complete reference

Source: https://story.runninghub.ai/zh-cn/ai-comic/open-api

Snapshot: 2026-10-18 (Asia/Taipei). Original source language and wire values are preserved.

Every operation includes its complete original OpenAPI object: parameters, request bodies, response schemas, examples, and extensions where present.

## Shared OpenAPI metadata and schemas

```json
{
  "openapi": "3.0.3",
  "info": {
    "title": "RH STORY 企业开放 API",
    "version": "v1"
  },
  "servers": [
    {
      "url": "https://story.runninghub.ai/aivideo/open/v1"
    }
  ],
  "tags": [
    {
      "name": "目录",
      "description": "查询当前可用的能力、生图 / 生视频应用、画风预设、导演风格与画幅比例，是发起后续所有生成类接口前的第一步。"
    },
    {
      "name": "文件",
      "description": "上传剧本 / 图片 / 音频文件，供一键导入项目、资产改图等接口引用。文件归属当前企业 Key，只有上传方自己能读取 / 删除。"
    },
    {
      "name": "一键导入",
      "description": "免去手动「建项目 → 建剧集 → 传剧本」的分步流程，一次提交完成建项目、按内容自动分集、规整剧本，异步任务；不会提取资产，任务成功后需再调用一次 POST /episodes/{episodeId}/asset-extractions。会分出几集、生成什么内容完全由剧本 / 创意内容决定，提交时无法预知。"
    },
    {
      "name": "剧本",
      "description": "在已创建的剧集内对剧本做更细粒度的操作：AI 润色、历史快照、内容类型检测、项目级重新提取资产。"
    },
    {
      "name": "自定义画风",
      "description": "管理用户自建的画风预设（区别于 GET /catalog/styles 返回的内置画风）。自定义画风归属调用方在网页端登录的用户，不是企业 Key 本身；同一用户在网页端创建的自定义画风也会出现在这里。"
    },
    {
      "name": "项目"
    },
    {
      "name": "剧集与剧本"
    },
    {
      "name": "资产"
    },
    {
      "name": "分场与分镜"
    },
    {
      "name": "镜头产出"
    },
    {
      "name": "成片与文件"
    },
    {
      "name": "任务"
    },
    {
      "name": "平台",
      "description": "任务重试、批量生图 / 生视频、用量与余额查询。"
    },
    {
      "name": "计费",
      "description": "LLM 计费任务（提资产 / 生分镜 / 单场重建 / 一键导入 / 项目生成 / 剧本润色 / 场次改写 / 项目重提取）按任务内模型调用的实际费用（网关标价，不加价）在任务终态一次性结算，每个任务一张账单：成功扣款，失败不扣，取消按已消耗量扣。生图 / 生视频 / 导出成片按各自通道计费，不在这里出账单。"
    },
    {
      "name": "Webhook 管理"
    }
  ],
  "security": [
    {
      "bearer": []
    }
  ],
  "components": {
    "securitySchemes": {
      "bearer": {
        "type": "http",
        "scheme": "bearer",
        "description": "企业 API Key，格式为 Bearer 加空格加 Key 原文。Key 从接入页“我的 Key”获取，仅企业共享（SHARED）类型的 Key 可调用本组接口，其他类型返回 403。"
      }
    },
    "schemas": {
      "ErrorResponse": {
        "type": "object",
        "required": [
          "code",
          "message"
        ],
        "properties": {
          "code": {
            "type": "string",
            "example": "DRAMA_BALANCE_INSUFFICIENT",
            "description": "仅出现在成功响应中，固定为 0。失败响应改用下方“错误响应示例”的独立结构，code 字段此时是字符串错误码（如 DRAMA_NOT_FOUND），且 HTTP 状态码不是 200，两种响应体结构不通用。"
          },
          "message": {
            "type": "string",
            "example": "余额不足，请充值后重试",
            "description": "仅出现在错误响应体中，人类可读的错误说明。"
          },
          "requestId": {
            "type": "string",
            "example": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab",
            "description": "仅出现在错误响应体中，用于排障的请求追踪 id，反馈问题时请附带。"
          }
        }
      }
    }
  }
}
```

## Contents

- [目录 (5)](#group-01)
- [文件 (3)](#group-02)
- [一键导入 (2)](#group-03)
- [剧本 (5)](#group-04)
- [自定义画风 (4)](#group-05)
- [项目 (6)](#group-06)
- [剧集与剧本 (7)](#group-07)
- [资产 (19)](#group-08)
- [分场与分镜 (11)](#group-09)
- [镜头产出 (15)](#group-10)
- [成片与文件 (3)](#group-11)
- [任务 (3)](#group-12)
- [平台 (7)](#group-13)
- [计费 (2)](#group-14)
- [Webhook 管理 (6)](#group-15)

<a id="group-01"></a>

## 目录

<a id="get-capabilities"></a>

### GET /capabilities - 能力清单

Operation ID: `get-capabilities`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=catalog-get-capabilities) | [Saved web text](web-pages/get-capabilities.txt)

查询当前企业 Key 可用的阶段与功能开关。

Complete operation specification:

```json
{
  "operationId": "get-capabilities",
  "summary": "能力清单",
  "description": "查询当前企业 Key 可用的阶段与功能开关。",
  "tags": [
    "目录"
  ],
  "responses": {
    "200": {
      "description": "能力清单",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "version": {
                    "type": "string",
                    "description": "接口版本号，当前恒为 v1。"
                  },
                  "site": {
                    "type": "string",
                    "description": "当前企业 Key 归属的部署站点：CN 国内站（runninghub.cn），AI 海外站（runninghub.ai）。",
                    "enum": [
                      "CN",
                      "AI"
                    ]
                  },
                  "baseUrl": {
                    "type": "string",
                    "description": "当前站点的 Base URL（含 basePath），与“开始使用”页展示的一致。"
                  },
                  "stages": {
                    "type": "array",
                    "items": {
                      "type": "string"
                    },
                    "description": "可用阶段清单，一期为写死值，不代表某个项目的当前实际进度（进度请查 GET /episodes/{episodeId}）。"
                  },
                  "rateLimit": {
                    "type": "object",
                    "properties": {
                      "replenishRatePerSecond": {
                        "type": "number",
                        "description": "每秒补充的令牌数。"
                      },
                      "burstCapacity": {
                        "type": "number",
                        "description": "令牌桶容量，即突发请求上限。"
                      }
                    },
                    "description": "当前企业 Key 的令牌桶限流参数，与 GET /quota 返回的 rateLimit 一致。"
                  },
                  "features": {
                    "type": "object",
                    "properties": {
                      "files": {
                        "type": "boolean",
                        "description": "是否开放文件上传（POST /files 等）。"
                      },
                      "projectImport": {
                        "type": "boolean",
                        "description": "是否开放一键导入（project-imports / project-generations）。"
                      },
                      "scriptTools": {
                        "type": "boolean",
                        "description": "是否开放剧本相关工具（AI 润色 / 快照 / 类型检测）。"
                      },
                      "editing": {
                        "type": "boolean",
                        "description": "是否开放分场 / 分镜编辑接口。"
                      },
                      "assetEditing": {
                        "type": "boolean",
                        "description": "是否开放资产改图与变体管理。"
                      },
                      "batchGeneration": {
                        "type": "boolean",
                        "description": "是否开放批量镜头生图 / 生视频。"
                      },
                      "taskRetry": {
                        "type": "boolean",
                        "description": "是否开放任务重试（POST /tasks/{taskNo}/retries）。"
                      },
                      "webhookDeliveries": {
                        "type": "boolean",
                        "description": "是否开放投递记录查询与手动重投。"
                      },
                      "usage": {
                        "type": "boolean",
                        "description": "是否开放用量 / 余额 / 配额查询。"
                      },
                      "sandbox": {
                        "type": "boolean",
                        "description": "是否处于沙箱模式，当前恒为 false，预留字段。"
                      }
                    },
                    "description": "按部署实例固定的功能开关，同一站点所有企业 Key 看到的值相同（不按 Key 灰度）。"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "version": "v1",
              "site": "CN",
              "baseUrl": "https://www.runninghub.cn/aivideo/open/v1",
              "stages": [
                "PROJECT",
                "EPISODE",
                "SCRIPT",
                "ASSETS",
                "SCENES",
                "STORYBOARD",
                "SHOTS",
                "FILM_EXPORT"
              ],
              "rateLimit": {
                "replenishRatePerSecond": 20,
                "burstCapacity": 40
              },
              "features": {
                "files": true,
                "projectImport": true,
                "scriptTools": true,
                "editing": true,
                "assetEditing": true,
                "batchGeneration": true,
                "taskRetry": true,
                "webhookDeliveries": true,
                "usage": true,
                "sandbox": false
              }
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  }
}
```

<a id="get-catalog-apps"></a>

### GET /catalog/apps - 应用目录

Operation ID: `get-catalog-apps`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=catalog-get-catalog-apps) | [Saved web text](web-pages/get-catalog-apps.txt)

查询生图 / 生视频可用应用。

Complete operation specification:

```json
{
  "operationId": "get-catalog-apps",
  "summary": "应用目录",
  "description": "查询生图 / 生视频可用应用。",
  "tags": [
    "目录"
  ],
  "responses": {
    "200": {
      "description": "应用目录",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "array",
                "items": {
                  "type": "object",
                  "properties": {
                    "appCode": {
                      "type": "string",
                      "description": "应用稳定码，传给生图 / 生视频接口的 appCode 字段。"
                    },
                    "name": {
                      "type": "string",
                      "description": "应用展示名。"
                    },
                    "capability": {
                      "type": "string",
                      "description": "能力维度。",
                      "enum": [
                        "IMAGE",
                        "VIDEO"
                      ]
                    },
                    "imageMode": {
                      "type": "string",
                      "description": "图生图（I2I）还是文生图（T2I）。",
                      "enum": [
                        "I2I",
                        "T2I"
                      ]
                    },
                    "skuId": {
                      "type": "string",
                      "description": "关联 SKU id；为避免精度丢失，数值以字符串形式返回。"
                    }
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": [
              {
                "appCode": "NANO_PRO_G2_I2I_OFFICIAL",
                "name": "Nano Pro G2（角色改图）",
                "capability": "IMAGE",
                "imageMode": "I2I",
                "skuId": "10234"
              }
            ]
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "capability",
      "in": "query",
      "required": true,
      "description": "按能力维度筛选：生图或生视频。",
      "schema": {
        "type": "string",
        "enum": [
          "IMAGE",
          "VIDEO"
        ]
      },
      "example": "IMAGE"
    },
    {
      "name": "usageScope",
      "in": "query",
      "required": false,
      "description": "按用途范围进一步收窄（不传则只按 capability 加站点可见加 SKU 白名单过滤，不做图生图 / 文生图收窄）。网页端「仅会员可用」的模型不对开放 API 提供。",
      "schema": {
        "type": "string",
        "enum": [
          "CHARACTER",
          "SCENE_PROP",
          "SCENE_PROP_EDIT",
          "FREE_CREATION_T2I",
          "FREE_CREATION_I2I"
        ]
      }
    }
  ]
}
```

<a id="get-catalog-styles"></a>

### GET /catalog/styles - 画风目录

Operation ID: `get-catalog-styles`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=catalog-get-catalog-styles) | [Saved web text](web-pages/get-catalog-styles.txt)

查询可用画风预设。

Complete operation specification:

```json
{
  "operationId": "get-catalog-styles",
  "summary": "画风目录",
  "description": "查询可用画风预设。",
  "tags": [
    "目录"
  ],
  "responses": {
    "200": {
      "description": "画风目录",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "array",
                "items": {
                  "type": "object",
                  "properties": {
                    "stylePresetId": {
                      "type": "string",
                      "description": "画风预设内部 id 的原样字符串（不是 OpenIds 编码），传给 asset-extractions 的 stylePresetId 字段。"
                    },
                    "name": {
                      "type": "string",
                      "description": "画风名称。"
                    },
                    "previewUrl": {
                      "type": "string",
                      "description": "预览图 URL。"
                    }
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": [
              {
                "stylePresetId": "88123",
                "name": "国风水墨",
                "previewUrl": "https://cdn.runninghub.cn/style/88123.png"
              }
            ]
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  }
}
```

<a id="get-catalog-director-styles"></a>

### GET /catalog/director-styles - 导演风格目录

Operation ID: `get-catalog-director-styles`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=catalog-get-catalog-director-styles) | [Saved web text](web-pages/get-catalog-director-styles.txt)

查询内置分镜导演风格，key 用于剧集设置的 directorStyleKey。

按部署站点（国内 / 海外）过滤可见性，只返回启用且未删除的风格，按后台排序权重升序。

Complete operation specification:

```json
{
  "operationId": "get-catalog-director-styles",
  "summary": "导演风格目录",
  "description": "查询内置分镜导演风格，key 用于剧集设置的 directorStyleKey。\n\n按部署站点（国内 / 海外）过滤可见性，只返回启用且未删除的风格，按后台排序权重升序。",
  "tags": [
    "目录"
  ],
  "responses": {
    "200": {
      "description": "导演风格目录",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "array",
                "items": {
                  "type": "object",
                  "properties": {
                    "key": {
                      "type": "string",
                      "description": "风格 key，传给 PUT /episodes/(episodeId)/settings 的 directorStyleKey 字段。"
                    },
                    "name": {
                      "type": "string",
                      "description": "风格名称。"
                    },
                    "description": {
                      "type": "string",
                      "description": "风格简介。"
                    },
                    "coverUrl": {
                      "type": "string",
                      "description": "封面图可访问地址。"
                    }
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": [
              {
                "key": "CINEMATIC_WIDE",
                "name": "电影感广角",
                "description": "大量广角与全景，强调空间感与氛围。",
                "coverUrl": "https://cdn.runninghub.cn/director-style/cinematic-wide.png"
              }
            ]
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  }
}
```

<a id="get-catalog-aspect-ratios"></a>

### GET /catalog/aspect-ratios - 画幅比例目录

Operation ID: `get-catalog-aspect-ratios`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=catalog-get-catalog-aspect-ratios) | [Saved web text](web-pages/get-catalog-aspect-ratios.txt)

查询平台支持的画幅比例常量，供 project-imports / project-generations 的 aspectRatio 字段取值。

当前恒为这两条固定值，不查库、不分页。

Complete operation specification:

```json
{
  "operationId": "get-catalog-aspect-ratios",
  "summary": "画幅比例目录",
  "description": "查询平台支持的画幅比例常量，供 project-imports / project-generations 的 aspectRatio 字段取值。\n\n当前恒为这两条固定值，不查库、不分页。",
  "tags": [
    "目录"
  ],
  "responses": {
    "200": {
      "description": "画幅比例目录",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "array",
                "items": {
                  "type": "object",
                  "properties": {
                    "value": {
                      "type": "string",
                      "description": "画幅比例字符串。"
                    },
                    "orientation": {
                      "type": "string",
                      "description": "对应的剧集取向。",
                      "enum": [
                        "LANDSCAPE",
                        "PORTRAIT"
                      ]
                    }
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": [
              {
                "value": "16:9",
                "orientation": "LANDSCAPE"
              },
              {
                "value": "9:16",
                "orientation": "PORTRAIT"
              }
            ]
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  }
}
```


<a id="group-02"></a>

## 文件

<a id="upload-file"></a>

### POST /files - 上传文件

Operation ID: `upload-file`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=files-upload-file) | [Saved web text](web-pages/upload-file.txt)

上传剧本、图片或音频文件，返回可供后续接口引用的文件号。

本接口用 multipart/form-data 提交，不是 application/json；file 字段放二进制内容，purpose 作为普通表单字段一起提交。

请求体不是合法的 multipart 表单、缺少 file 字段、file 为空文件，或 purpose 不是 SCRIPT / IMAGE / AUDIO 之一，返回 422 DRAMA_VALIDATION_FAILED。

purpose=SCRIPT 时允许 txt、md、docx、xlsx、pdf 五种扩展名；purpose=IMAGE 允许 png、jpg、jpeg、webp；purpose=AUDIO 允许 mp3、wav、m4a。扩展名不在白名单返回 415 DRAMA_FILE_UNSUPPORTED。

文档承诺的大小上限是 20MB，但当前网关 multipart 全局配置上限是 10MB，早于本接口自身校验生效——实际能上传成功的上限目前是 10MB，超限统一映射为 413 DRAMA_FILE_TOO_LARGE。这是已知差异，等后端把全局配置提到 20MB 后才会名副其实，调用前建议按 10MB 控制文件体积。

purpose=SCRIPT 时会同步解析正文：txt/md 按 UTF-8 直读，docx/xlsx/pdf 走服务端文本提取；解析失败返回 422 DRAMA_FILE_PARSE_FAILED，解析出的正文为空返回 422 DRAMA_SCRIPT_INVALID。

不支持 Idempotency-Key，每次调用都会新建一条文件记录。

Complete operation specification:

```json
{
  "operationId": "upload-file",
  "summary": "上传文件",
  "description": "上传剧本、图片或音频文件，返回可供后续接口引用的文件号。\n\n本接口用 multipart/form-data 提交，不是 application/json；file 字段放二进制内容，purpose 作为普通表单字段一起提交。\n\n请求体不是合法的 multipart 表单、缺少 file 字段、file 为空文件，或 purpose 不是 SCRIPT / IMAGE / AUDIO 之一，返回 422 DRAMA_VALIDATION_FAILED。\n\npurpose=SCRIPT 时允许 txt、md、docx、xlsx、pdf 五种扩展名；purpose=IMAGE 允许 png、jpg、jpeg、webp；purpose=AUDIO 允许 mp3、wav、m4a。扩展名不在白名单返回 415 DRAMA_FILE_UNSUPPORTED。\n\n文档承诺的大小上限是 20MB，但当前网关 multipart 全局配置上限是 10MB，早于本接口自身校验生效——实际能上传成功的上限目前是 10MB，超限统一映射为 413 DRAMA_FILE_TOO_LARGE。这是已知差异，等后端把全局配置提到 20MB 后才会名副其实，调用前建议按 10MB 控制文件体积。\n\npurpose=SCRIPT 时会同步解析正文：txt/md 按 UTF-8 直读，docx/xlsx/pdf 走服务端文本提取；解析失败返回 422 DRAMA_FILE_PARSE_FAILED，解析出的正文为空返回 422 DRAMA_SCRIPT_INVALID。\n\n不支持 Idempotency-Key，每次调用都会新建一条文件记录。",
  "tags": [
    "文件"
  ],
  "responses": {
    "200": {
      "description": "上传文件",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "fileId": {
                    "type": "string",
                    "description": "对外文件号，up_ 前缀。"
                  },
                  "fileName": {
                    "type": "string",
                    "description": "原始文件名。"
                  },
                  "size": {
                    "type": "string",
                    "description": "文件大小，单位字节；64 位整数以数字字符串返回。"
                  },
                  "contentType": {
                    "type": "string",
                    "description": "MIME 类型，剧本文件按扩展名映射（如 docx 对应 openxml 类型），图片 / 音频取上传时声明的类型，取不到则为 application/octet-stream。"
                  },
                  "purpose": {
                    "type": "string",
                    "description": "文件用途。",
                    "enum": [
                      "SCRIPT",
                      "IMAGE",
                      "AUDIO"
                    ]
                  },
                  "textLength": {
                    "type": "number",
                    "description": "仅 purpose=SCRIPT 时非空：服务端解析出的正文字符数。"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "fileId": "up_3Fq8Nx2",
              "fileName": "ep01.docx",
              "size": "24576",
              "contentType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
              "purpose": "SCRIPT",
              "textLength": 3421
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "requestBody": {
    "required": true,
    "content": {
      "multipart/form-data": {
        "schema": {
          "type": "object",
          "properties": {
            "file": {
              "type": "string",
              "format": "binary",
              "description": "二进制文件内容，multipart 表单字段名固定为 file。"
            },
            "purpose": {
              "type": "string",
              "enum": [
                "SCRIPT",
                "IMAGE",
                "AUDIO"
              ],
              "description": "文件用途，决定允许的扩展名与是否解析正文；不传按 SCRIPT 处理。"
            }
          },
          "required": [
            "file"
          ]
        }
      }
    }
  }
}
```

<a id="get-file"></a>

### GET /files/{fileId} - 查询文件

Operation ID: `get-file`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=files-get-file) | [Saved web text](web-pages/get-file.txt)

按文件号查询元数据。

不属于当前企业 Key 或 id 不合法都返回 404 DRAMA_NOT_FOUND。

Complete operation specification:

```json
{
  "operationId": "get-file",
  "summary": "查询文件",
  "description": "按文件号查询元数据。\n\n不属于当前企业 Key 或 id 不合法都返回 404 DRAMA_NOT_FOUND。",
  "tags": [
    "文件"
  ],
  "responses": {
    "200": {
      "description": "查询文件",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "fileId": {
                    "type": "string",
                    "description": "对外文件号。"
                  },
                  "fileName": {
                    "type": "string",
                    "description": "原始文件名。"
                  },
                  "size": {
                    "type": "string",
                    "description": "文件大小，单位字节；64 位整数以数字字符串返回。"
                  },
                  "contentType": {
                    "type": "string",
                    "description": "MIME 类型。"
                  },
                  "purpose": {
                    "type": "string",
                    "description": "文件用途。",
                    "enum": [
                      "SCRIPT",
                      "IMAGE",
                      "AUDIO"
                    ]
                  },
                  "textLength": {
                    "type": "number",
                    "description": "仅 purpose=SCRIPT 时非空。"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "fileId": "up_3Fq8Nx2",
              "fileName": "ep01.docx",
              "size": "24576",
              "contentType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
              "purpose": "SCRIPT",
              "textLength": 3421
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "fileId",
      "in": "path",
      "required": true,
      "description": "对外文件号。",
      "schema": {
        "type": "string"
      },
      "example": "up_3Fq8Nx2"
    }
  ]
}
```

<a id="delete-file"></a>

### DELETE /files/{fileId} - 删除文件

Operation ID: `delete-file`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=files-delete-file) | [Saved web text](web-pages/delete-file.txt)

删除一个已上传文件及其存储对象。

已被 project-imports 或资产改图引用过的文件仍可删除，不影响已生成的项目 / 图片，但已经用掉的 fileId 之后再引用会返回 404。

Complete operation specification:

```json
{
  "operationId": "delete-file",
  "summary": "删除文件",
  "description": "删除一个已上传文件及其存储对象。\n\n已被 project-imports 或资产改图引用过的文件仍可删除，不影响已生成的项目 / 图片，但已经用掉的 fileId 之后再引用会返回 404。",
  "tags": [
    "文件"
  ],
  "responses": {
    "200": {
      "description": "删除文件",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "nullable": true
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": null
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "fileId",
      "in": "path",
      "required": true,
      "description": "对外文件号。",
      "schema": {
        "type": "string"
      },
      "example": "up_3Fq8Nx2"
    }
  ]
}
```


<a id="group-03"></a>

## 一键导入

<a id="import-project"></a>

### POST /project-imports - 导入剧本建项目

Operation ID: `import-project`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=quick-import-import-project) | [Saved web text](web-pages/import-project.txt)

用已有剧本一次性建项目、自动分集、规整剧本，异步任务。只做剧本规整 + 自动分集 + 建项目，不会拆分场次、不会提取资产。

scriptFileId 与 scriptContent 必须二选一，都传或都不传返回 400 DRAMA_REQUEST_FAILED；scriptContent 为空白或 scriptFileId 指向的文件不是已成功解析出文本的 purpose=SCRIPT 文件，返回 422 DRAMA_SCRIPT_INVALID；剧本字数超出平台单次上限返回 400 DRAMA_REQUEST_FAILED。

一次调用可能按内容拆出多集，episodeId 只给第一集，全部剧集见 result.episodes（也可用 GET /projects/(projectId)/episodes 翻页获取）。result 里不再包含网页端专用字段。

导入只做剧本规整 + 自动分集 + 建项目，不会拆分场次、不会提取资产。任务内还会提取标题、生成项目简介 / 人物介绍 / 各集概述，并把概述与人物介绍前置到第一集剧本开头；这些模型调用都计入本任务账单。任务 SUCCEEDED 后，取 result.episodes 中任意一集调用一次 POST /episodes/{episodeId}/asset-extractions 即可：首次提取为项目级，对整本剧本一次完成场次拆分与资产提取、覆盖全部剧集（与网页端「确认剧本」一致），之后才能生成分镜；按 ASSET_EXTRACT 单独计费。

aspectRatio / stylePresetId 会实际写入自动创建的每一集；contentLanguage 目前只接收不生效（内部快速生成流程没有对应的语言覆盖参数）。

通过本接口创建的项目同样打上 source=OPEN_API 标记，在网页端工作台可见。

计费：按任务内模型调用的实际费用（网关标价，不加价）在任务终态一次性结算——成功扣款，失败不扣，取消按已消耗量扣（含取消时仍在进行的调用，账单在任务实际停止后结算）；金额按分四舍五入；模型由平台统一配置，不可指定。提交时余额需大于 0（团队 Key 看团队钱包，非团队 Key 看企业账户余额），否则返回 402 DRAMA_BALANCE_INSUFFICIENT；结算可能把余额扣成负数，之后的计费任务会被拦截直到充值。结算时若因系统原因扣款失败，账单记为欠费（ARREARS / ARREARS_PARTIAL_CANCELED），由平台自动补扣，不影响继续提交。任务从提交到终态占用一个企业 Key 并发名额（GET /quota 的 concurrentLimit），已满返回 429 DRAMA_CONCURRENCY_LIMIT，稍后重试。可用 GET /bills 查账单。

Complete operation specification:

```json
{
  "operationId": "import-project",
  "summary": "导入剧本建项目",
  "description": "用已有剧本一次性建项目、自动分集、规整剧本，异步任务。只做剧本规整 + 自动分集 + 建项目，不会拆分场次、不会提取资产。\n\nscriptFileId 与 scriptContent 必须二选一，都传或都不传返回 400 DRAMA_REQUEST_FAILED；scriptContent 为空白或 scriptFileId 指向的文件不是已成功解析出文本的 purpose=SCRIPT 文件，返回 422 DRAMA_SCRIPT_INVALID；剧本字数超出平台单次上限返回 400 DRAMA_REQUEST_FAILED。\n\n一次调用可能按内容拆出多集，episodeId 只给第一集，全部剧集见 result.episodes（也可用 GET /projects/(projectId)/episodes 翻页获取）。result 里不再包含网页端专用字段。\n\n导入只做剧本规整 + 自动分集 + 建项目，不会拆分场次、不会提取资产。任务内还会提取标题、生成项目简介 / 人物介绍 / 各集概述，并把概述与人物介绍前置到第一集剧本开头；这些模型调用都计入本任务账单。任务 SUCCEEDED 后，取 result.episodes 中任意一集调用一次 POST /episodes/{episodeId}/asset-extractions 即可：首次提取为项目级，对整本剧本一次完成场次拆分与资产提取、覆盖全部剧集（与网页端「确认剧本」一致），之后才能生成分镜；按 ASSET_EXTRACT 单独计费。\n\naspectRatio / stylePresetId 会实际写入自动创建的每一集；contentLanguage 目前只接收不生效（内部快速生成流程没有对应的语言覆盖参数）。\n\n通过本接口创建的项目同样打上 source=OPEN_API 标记，在网页端工作台可见。\n\n计费：按任务内模型调用的实际费用（网关标价，不加价）在任务终态一次性结算——成功扣款，失败不扣，取消按已消耗量扣（含取消时仍在进行的调用，账单在任务实际停止后结算）；金额按分四舍五入；模型由平台统一配置，不可指定。提交时余额需大于 0（团队 Key 看团队钱包，非团队 Key 看企业账户余额），否则返回 402 DRAMA_BALANCE_INSUFFICIENT；结算可能把余额扣成负数，之后的计费任务会被拦截直到充值。结算时若因系统原因扣款失败，账单记为欠费（ARREARS / ARREARS_PARTIAL_CANCELED），由平台自动补扣，不影响继续提交。任务从提交到终态占用一个企业 Key 并发名额（GET /quota 的 concurrentLimit），已满返回 429 DRAMA_CONCURRENCY_LIMIT，稍后重试。可用 GET /bills 查账单。",
  "tags": [
    "一键导入"
  ],
  "responses": {
    "200": {
      "description": "导入剧本建项目",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "taskId": {
                    "type": "string",
                    "description": "任务号。"
                  },
                  "type": {
                    "type": "string",
                    "description": "固定为 PROJECT_IMPORT。"
                  },
                  "status": {
                    "type": "string"
                  },
                  "progress": {
                    "nullable": true
                  },
                  "result": {
                    "nullable": true,
                    "description": "SUCCEEDED 后为 projectId、episodeId、episodeCount 三个字段：projectId 是新建项目的对外 id（pj_ 前缀），episodeId 是拆出的第一集的对外 id（ep_ 前缀），可直接用于 GET /projects/(projectId)、GET /episodes/(episodeId) 等后续调用；episodeCount 是本次实际创建的剧集数；episodes 是本次创建的全部剧集数组，每项为 {episodeId, episodeIndex, title}，episodeIndex 从 1 起，例：[{\"episodeId\":\"ep_4Rt7QxNp1\",\"episodeIndex\":1,\"title\":\"第一集\"}]。"
                  },
                  "error": {
                    "nullable": true
                  },
                  "cost": {
                    "nullable": true
                  },
                  "createdAt": {
                    "type": "string"
                  },
                  "finishedAt": {
                    "nullable": true
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "taskId": "tk_2Cv9Qw1",
              "type": "PROJECT_IMPORT",
              "status": "QUEUED",
              "progress": null,
              "result": null,
              "error": null,
              "cost": null,
              "createdAt": "2026-09-17T09:00:00.000+08:00",
              "finishedAt": null
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "Idempotency-Key",
      "in": "header",
      "required": false,
      "description": "幂等键，按（企业 Key，该值）24 小时内去重。",
      "schema": {
        "type": "string"
      }
    }
  ],
  "requestBody": {
    "required": false,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "scriptFileId": {
              "type": "string",
              "description": "剧本文件号（up_ 前缀），来自 POST /files 且 purpose=SCRIPT；与 scriptContent 二选一。"
            },
            "scriptContent": {
              "type": "string",
              "description": "剧本文本内容；与 scriptFileId 二选一。"
            },
            "scriptFileName": {
              "type": "string",
              "description": "剧本文件名，仅展示用途；传 scriptFileId 时缺省取该文件的原始文件名。"
            },
            "aspectRatio": {
              "type": "string",
              "enum": [
                "16:9",
                "9:16"
              ],
              "description": "画幅，写入自动创建的每一集的取向；不传则不设置（沿用系统默认）。"
            },
            "contentLanguage": {
              "type": "string",
              "description": "当前只接收、不生效，内部流水线暂无对应的语言覆盖入口，见下方备注。"
            },
            "stylePresetId": {
              "type": "string",
              "description": "画风预设 id，取自 GET /catalog/styles 的 stylePresetId（不是自定义画风的 st_ 前缀 id），写入每一集；非数字字符串返回 422 DRAMA_STYLE_NOT_FOUND（提交时不校验该 id 是否真实存在）。"
            },
            "title": {
              "type": "string",
              "description": "项目标题覆盖；不传则按剧本内容自动生成。"
            }
          }
        },
        "example": {
          "scriptFileId": "up_3Fq8Nx2",
          "aspectRatio": "16:9",
          "stylePresetId": "88123",
          "title": "霓虹都市"
        }
      }
    }
  }
}
```

<a id="generate-project"></a>

### POST /project-generations - AI 创意生成项目

Operation ID: `generate-project`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=quick-import-generate-project) | [Saved web text](web-pages/generate-project.txt)

用一句创意想法一次性生成剧本、建项目、自动分集并规整剧本，异步任务。

idea 生成的耗时高于导入既有剧本（要先由 AI 编写完整剧本，再走同样的建项目 / 分集 / 规整剧本步骤）；agent 模式通常只产出一集，但不要假设 episodeCount 恒为 1。

导入只做剧本规整 + 自动分集 + 建项目，不会拆分场次、不会提取资产。任务内还会提取标题、生成项目简介 / 人物介绍 / 各集概述，并把概述与人物介绍前置到第一集剧本开头；这些模型调用都计入本任务账单。任务 SUCCEEDED 后，取 result.episodes 中任意一集调用一次 POST /episodes/{episodeId}/asset-extractions 即可：首次提取为项目级，对整本剧本一次完成场次拆分与资产提取、覆盖全部剧集（与网页端「确认剧本」一致），之后才能生成分镜；按 ASSET_EXTRACT 单独计费。

其余行为（result 结构、source 标记）同「导入剧本建项目」。

计费：按任务内模型调用的实际费用（网关标价，不加价）在任务终态一次性结算——成功扣款，失败不扣，取消按已消耗量扣（含取消时仍在进行的调用，账单在任务实际停止后结算）；金额按分四舍五入；模型由平台统一配置，不可指定。提交时余额需大于 0（团队 Key 看团队钱包，非团队 Key 看企业账户余额），否则返回 402 DRAMA_BALANCE_INSUFFICIENT；结算可能把余额扣成负数，之后的计费任务会被拦截直到充值。结算时若因系统原因扣款失败，账单记为欠费（ARREARS / ARREARS_PARTIAL_CANCELED），由平台自动补扣，不影响继续提交。任务从提交到终态占用一个企业 Key 并发名额（GET /quota 的 concurrentLimit），已满返回 429 DRAMA_CONCURRENCY_LIMIT，稍后重试。可用 GET /bills 查账单。

Complete operation specification:

```json
{
  "operationId": "generate-project",
  "summary": "AI 创意生成项目",
  "description": "用一句创意想法一次性生成剧本、建项目、自动分集并规整剧本，异步任务。\n\nidea 生成的耗时高于导入既有剧本（要先由 AI 编写完整剧本，再走同样的建项目 / 分集 / 规整剧本步骤）；agent 模式通常只产出一集，但不要假设 episodeCount 恒为 1。\n\n导入只做剧本规整 + 自动分集 + 建项目，不会拆分场次、不会提取资产。任务内还会提取标题、生成项目简介 / 人物介绍 / 各集概述，并把概述与人物介绍前置到第一集剧本开头；这些模型调用都计入本任务账单。任务 SUCCEEDED 后，取 result.episodes 中任意一集调用一次 POST /episodes/{episodeId}/asset-extractions 即可：首次提取为项目级，对整本剧本一次完成场次拆分与资产提取、覆盖全部剧集（与网页端「确认剧本」一致），之后才能生成分镜；按 ASSET_EXTRACT 单独计费。\n\n其余行为（result 结构、source 标记）同「导入剧本建项目」。\n\n计费：按任务内模型调用的实际费用（网关标价，不加价）在任务终态一次性结算——成功扣款，失败不扣，取消按已消耗量扣（含取消时仍在进行的调用，账单在任务实际停止后结算）；金额按分四舍五入；模型由平台统一配置，不可指定。提交时余额需大于 0（团队 Key 看团队钱包，非团队 Key 看企业账户余额），否则返回 402 DRAMA_BALANCE_INSUFFICIENT；结算可能把余额扣成负数，之后的计费任务会被拦截直到充值。结算时若因系统原因扣款失败，账单记为欠费（ARREARS / ARREARS_PARTIAL_CANCELED），由平台自动补扣，不影响继续提交。任务从提交到终态占用一个企业 Key 并发名额（GET /quota 的 concurrentLimit），已满返回 429 DRAMA_CONCURRENCY_LIMIT，稍后重试。可用 GET /bills 查账单。",
  "tags": [
    "一键导入"
  ],
  "responses": {
    "200": {
      "description": "AI 创意生成项目",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "taskId": {
                    "type": "string",
                    "description": "任务号。"
                  },
                  "type": {
                    "type": "string",
                    "description": "固定为 PROJECT_GENERATE。"
                  },
                  "status": {
                    "type": "string"
                  },
                  "progress": {
                    "nullable": true
                  },
                  "result": {
                    "nullable": true,
                    "description": "SUCCEEDED 后结构同「导入剧本建项目」：projectId（pj_ 前缀）、episodeId（ep_ 前缀）、episodeCount、episodes（[{episodeId, episodeIndex, title}]，episodeIndex 从 1 起）四个字段。"
                  },
                  "error": {
                    "nullable": true
                  },
                  "cost": {
                    "nullable": true
                  },
                  "createdAt": {
                    "type": "string"
                  },
                  "finishedAt": {
                    "nullable": true
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "taskId": "tk_3Dw1Rx2",
              "type": "PROJECT_GENERATE",
              "status": "QUEUED",
              "progress": null,
              "result": null,
              "error": null,
              "cost": null,
              "createdAt": "2026-09-17T09:05:00.000+08:00",
              "finishedAt": null
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "Idempotency-Key",
      "in": "header",
      "required": false,
      "description": "幂等键，按（企业 Key，该值）24 小时内去重。",
      "schema": {
        "type": "string"
      }
    }
  ],
  "requestBody": {
    "required": true,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "idea": {
              "type": "string",
              "description": "创意想法文本，AI 据此生成完整剧本。"
            },
            "aspectRatio": {
              "type": "string",
              "enum": [
                "16:9",
                "9:16"
              ],
              "description": "画幅，写入自动创建的每一集的取向；不传则不设置。"
            },
            "contentLanguage": {
              "type": "string",
              "description": "当前只接收、不生效，同「导入剧本建项目」备注。"
            },
            "stylePresetId": {
              "type": "string",
              "description": "画风预设 id，取自 GET /catalog/styles 的 stylePresetId；非数字字符串返回 422 DRAMA_STYLE_NOT_FOUND（不校验是否真实存在）。"
            },
            "title": {
              "type": "string",
              "description": "项目标题覆盖；不传则按生成内容自动生成。"
            }
          },
          "required": [
            "idea"
          ]
        },
        "example": {
          "idea": "一个赛博朋克都市里侦探与仿生人的悬疑故事",
          "aspectRatio": "9:16"
        }
      }
    }
  }
}
```


<a id="group-04"></a>

## 剧本

<a id="refine-script"></a>

### POST /episodes/{episodeId}/script-refinements - AI 润色剧本

Operation ID: `refine-script`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=script-refine-script) | [Saved web text](web-pages/refine-script.txt)

按指令用 AI 改写该集剧本正文，异步任务。

计费：按任务内模型调用的实际费用（网关标价，不加价）在任务终态一次性结算——成功扣款，失败不扣，取消按已消耗量扣（含取消时仍在进行的调用，账单在任务实际停止后结算）；金额按分四舍五入；模型由平台统一配置，不可指定。提交时余额需大于 0（团队 Key 看团队钱包，非团队 Key 看企业账户余额），否则返回 402 DRAMA_BALANCE_INSUFFICIENT；结算可能把余额扣成负数，之后的计费任务会被拦截直到充值。结算时若因系统原因扣款失败，账单记为欠费（ARREARS / ARREARS_PARTIAL_CANCELED），由平台自动补扣，不影响继续提交。任务从提交到终态占用一个企业 Key 并发名额（GET /quota 的 concurrentLimit），已满返回 429 DRAMA_CONCURRENCY_LIMIT，稍后重试。可用 GET /bills 查账单。

Complete operation specification:

```json
{
  "operationId": "refine-script",
  "summary": "AI 润色剧本",
  "description": "按指令用 AI 改写该集剧本正文，异步任务。\n\n计费：按任务内模型调用的实际费用（网关标价，不加价）在任务终态一次性结算——成功扣款，失败不扣，取消按已消耗量扣（含取消时仍在进行的调用，账单在任务实际停止后结算）；金额按分四舍五入；模型由平台统一配置，不可指定。提交时余额需大于 0（团队 Key 看团队钱包，非团队 Key 看企业账户余额），否则返回 402 DRAMA_BALANCE_INSUFFICIENT；结算可能把余额扣成负数，之后的计费任务会被拦截直到充值。结算时若因系统原因扣款失败，账单记为欠费（ARREARS / ARREARS_PARTIAL_CANCELED），由平台自动补扣，不影响继续提交。任务从提交到终态占用一个企业 Key 并发名额（GET /quota 的 concurrentLimit），已满返回 429 DRAMA_CONCURRENCY_LIMIT，稍后重试。可用 GET /bills 查账单。",
  "tags": [
    "剧本"
  ],
  "responses": {
    "200": {
      "description": "AI 润色剧本",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "taskId": {
                    "type": "string",
                    "description": "任务号。"
                  },
                  "type": {
                    "type": "string",
                    "description": "固定为 SCRIPT_REFINE。"
                  },
                  "status": {
                    "type": "string"
                  },
                  "progress": {
                    "nullable": true
                  },
                  "result": {
                    "nullable": true,
                    "description": "SUCCEEDED 后内容以内部润色接口的实际返回为准（一般含改写后的剧本快照信息）；具体字段未强类型约定，建议成功后另外调用 GET /episodes/(episodeId)/script/versions 拿最新快照。"
                  },
                  "error": {
                    "nullable": true
                  },
                  "cost": {
                    "nullable": true
                  },
                  "createdAt": {
                    "type": "string"
                  },
                  "finishedAt": {
                    "nullable": true
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "taskId": "tk_4Ey3Rz9",
              "type": "SCRIPT_REFINE",
              "status": "QUEUED",
              "progress": null,
              "result": null,
              "error": null,
              "cost": null,
              "createdAt": "2026-09-17T09:15:00.000+08:00",
              "finishedAt": null
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "Idempotency-Key",
      "in": "header",
      "required": false,
      "description": "幂等键。",
      "schema": {
        "type": "string"
      }
    },
    {
      "name": "episodeId",
      "in": "path",
      "required": true,
      "description": "对外剧集号。",
      "schema": {
        "type": "string"
      },
      "example": "ep_4Rt7QxNp1"
    }
  ],
  "requestBody": {
    "required": true,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "instruction": {
              "type": "string",
              "description": "改写指令，如“把第二场的雨夜氛围写得更压抑”。"
            },
            "forceRefresh": {
              "type": "boolean",
              "description": "强制重跑，绕过 LLM 幂等缓存；默认 false。"
            }
          },
          "required": [
            "instruction"
          ]
        },
        "example": {
          "instruction": "把第二场的雨夜氛围写得更压抑"
        }
      }
    }
  }
}
```

<a id="list-script-versions"></a>

### GET /episodes/{episodeId}/script/versions - 剧本快照列表

Operation ID: `list-script-versions`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=script-list-script-versions) | [Saved web text](web-pages/list-script-versions.txt)

查询该集全部剧本快照（不含正文，不分页）。

按创建时间返回全部快照，不分页；数量随改写次数增长，客户端如需限制可自行按 createdAt 截取。

Complete operation specification:

```json
{
  "operationId": "list-script-versions",
  "summary": "剧本快照列表",
  "description": "查询该集全部剧本快照（不含正文，不分页）。\n\n按创建时间返回全部快照，不分页；数量随改写次数增长，客户端如需限制可自行按 createdAt 截取。",
  "tags": [
    "剧本"
  ],
  "responses": {
    "200": {
      "description": "剧本快照列表",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "array",
                "items": {
                  "type": "object",
                  "properties": {
                    "versionId": {
                      "type": "string",
                      "description": "对外快照号，sv_ 前缀。"
                    },
                    "episodeId": {
                      "type": "string",
                      "description": "所属剧集号。"
                    },
                    "version": {
                      "type": "number",
                      "description": "快照版本号，同集内递增。"
                    },
                    "source": {
                      "type": "string",
                      "description": "快照来源。",
                      "enum": [
                        "RAW_INPUT",
                        "AI_GENERATED",
                        "AI_REFINED",
                        "IMPORTED",
                        "AGGREGATED"
                      ]
                    },
                    "structureStatus": {
                      "type": "string",
                      "description": "AI 结构化状态：PENDING 已入库待处理、GENERATING 结构化中、DONE 已完成 / 无需结构化、FAILED 结构化失败（正文保留原文）。",
                      "enum": [
                        "PENDING",
                        "GENERATING",
                        "DONE",
                        "FAILED"
                      ]
                    },
                    "createdAt": {
                      "type": "string",
                      "description": "ISO-8601 创建时间。"
                    }
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": [
              {
                "versionId": "sv_5Ex2Qy8",
                "episodeId": "ep_4Rt7QxNp1",
                "version": 3,
                "source": "AI_REFINED",
                "structureStatus": "DONE",
                "createdAt": "2026-09-17T09:15:40.000+08:00"
              }
            ]
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "episodeId",
      "in": "path",
      "required": true,
      "description": "对外剧集号。",
      "schema": {
        "type": "string"
      },
      "example": "ep_4Rt7QxNp1"
    }
  ]
}
```

<a id="get-script-version"></a>

### GET /episodes/{episodeId}/script/versions/{versionId} - 剧本快照详情

Operation ID: `get-script-version`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=script-get-script-version) | [Saved web text](web-pages/get-script-version.txt)

按快照号查询详情，含正文。

versionId 不属于路径里的 episodeId 时返回 404 DRAMA_NOT_FOUND（即便该快照本身存在且属于你的 Key）。

Complete operation specification:

```json
{
  "operationId": "get-script-version",
  "summary": "剧本快照详情",
  "description": "按快照号查询详情，含正文。\n\nversionId 不属于路径里的 episodeId 时返回 404 DRAMA_NOT_FOUND（即便该快照本身存在且属于你的 Key）。",
  "tags": [
    "剧本"
  ],
  "responses": {
    "200": {
      "description": "剧本快照详情",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "versionId": {
                    "type": "string",
                    "description": "对外快照号。"
                  },
                  "episodeId": {
                    "type": "string",
                    "description": "所属剧集号。"
                  },
                  "version": {
                    "type": "number",
                    "description": "快照版本号。"
                  },
                  "source": {
                    "type": "string",
                    "description": "快照来源。",
                    "enum": [
                      "RAW_INPUT",
                      "AI_GENERATED",
                      "AI_REFINED",
                      "IMPORTED",
                      "AGGREGATED"
                    ]
                  },
                  "content": {
                    "type": "string",
                    "description": "剧本正文。"
                  },
                  "title": {
                    "nullable": true,
                    "description": "快照标题，多数场景为空。"
                  },
                  "note": {
                    "nullable": true,
                    "description": "快照备注，多数场景为空。"
                  },
                  "structureStatus": {
                    "type": "string",
                    "description": "AI 结构化状态。",
                    "enum": [
                      "PENDING",
                      "GENERATING",
                      "DONE",
                      "FAILED"
                    ]
                  },
                  "createdAt": {
                    "type": "string",
                    "description": "ISO-8601 创建时间。"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "versionId": "sv_5Ex2Qy8",
              "episodeId": "ep_4Rt7QxNp1",
              "version": 3,
              "source": "AI_REFINED",
              "content": "第一集\n场景一：雨夜街头……（润色版）",
              "title": null,
              "note": null,
              "structureStatus": "DONE",
              "createdAt": "2026-09-17T09:15:40.000+08:00"
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "episodeId",
      "in": "path",
      "required": true,
      "description": "对外剧集号。",
      "schema": {
        "type": "string"
      },
      "example": "ep_4Rt7QxNp1"
    },
    {
      "name": "versionId",
      "in": "path",
      "required": true,
      "description": "对外快照号。",
      "schema": {
        "type": "string"
      },
      "example": "sv_5Ex2Qy8"
    }
  ]
}
```

<a id="detect-script-type"></a>

### POST /script-detections - 检测内容类型

Operation ID: `detect-script-type`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=script-detect-script-type) | [Saved web text](web-pages/detect-script-type.txt)

判断一段文本更像剧本正文还是分镜脚本，用于导入前预判。

无状态判断，不关联任何项目 / 剧集，不做归属校验，不计费、不占并发位；text 为空、不传或超过 200000 字符返回 422 DRAMA_VALIDATION_FAILED。

内部先按关键词粗筛（命中 3 个以上镜头相关词直接判 storyboard），命中不足再调用 LLM 二次判断；LLM 调用异常时兜底返回 script。

Complete operation specification:

```json
{
  "operationId": "detect-script-type",
  "summary": "检测内容类型",
  "description": "判断一段文本更像剧本正文还是分镜脚本，用于导入前预判。\n\n无状态判断，不关联任何项目 / 剧集，不做归属校验，不计费、不占并发位；text 为空、不传或超过 200000 字符返回 422 DRAMA_VALIDATION_FAILED。\n\n内部先按关键词粗筛（命中 3 个以上镜头相关词直接判 storyboard），命中不足再调用 LLM 二次判断；LLM 调用异常时兜底返回 script。",
  "tags": [
    "剧本"
  ],
  "responses": {
    "200": {
      "description": "检测内容类型",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "type": {
                    "type": "string",
                    "description": "检测结果。",
                    "enum": [
                      "script",
                      "storyboard"
                    ]
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "type": "storyboard"
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "requestBody": {
    "required": true,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "text": {
              "type": "string",
              "description": "待检测文本，不能为空（为空或全空白返回 422 DRAMA_VALIDATION_FAILED），上限 200000 字符；超过 3000 字只取前 3000 字判断。"
            }
          },
          "required": [
            "text"
          ]
        },
        "example": {
          "text": "镜头 1：雨夜街头，特写，林夏疾步奔跑……"
        }
      }
    }
  }
}
```

<a id="reextract-project-assets"></a>

### POST /projects/{projectId}/asset-reextractions - 项目级重新提取资产

Operation ID: `reextract-project-assets`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=script-reextract-project-assets) | [Saved web text](web-pages/reextract-project-assets.txt)

对整个项目重新跑一次资产提取（覆盖项目下所有剧集），异步任务。

影响范围是整个项目（覆盖其下所有剧集的资产提取结果），不是单集操作；请在确认要整项目重来后再调用。

剧本已修改但尚未重新确认场次时，提交即同步返回 409 DRAMA_STAGE_PRECONDITION，不会创建任务。更新剧本（PUT /episodes/{episodeId}/script）、AI 润色剧本、手动新建场次、编辑场次正文、合并场次、AI 改写场次都会让场次与剧本失去对齐，需先调用 POST /episodes/{episodeId}/asset-extractions 按最新剧本重新确认场次。注意：重新确认会按最新剧本重新拆分该集场次并归档旧场次 / 分镜 / 视频，手动做的场次编辑会被覆盖；如需改内容，建议改剧本后重新确认，而不是直接改场次（与网页端行为一致）。

计费：按任务内模型调用的实际费用（网关标价，不加价）在任务终态一次性结算——成功扣款，失败不扣，取消按已消耗量扣（含取消时仍在进行的调用，账单在任务实际停止后结算）；金额按分四舍五入；模型由平台统一配置，不可指定。提交时余额需大于 0（团队 Key 看团队钱包，非团队 Key 看企业账户余额），否则返回 402 DRAMA_BALANCE_INSUFFICIENT；结算可能把余额扣成负数，之后的计费任务会被拦截直到充值。结算时若因系统原因扣款失败，账单记为欠费（ARREARS / ARREARS_PARTIAL_CANCELED），由平台自动补扣，不影响继续提交。任务从提交到终态占用一个企业 Key 并发名额（GET /quota 的 concurrentLimit），已满返回 429 DRAMA_CONCURRENCY_LIMIT，稍后重试。可用 GET /bills 查账单。

Complete operation specification:

```json
{
  "operationId": "reextract-project-assets",
  "summary": "项目级重新提取资产",
  "description": "对整个项目重新跑一次资产提取（覆盖项目下所有剧集），异步任务。\n\n影响范围是整个项目（覆盖其下所有剧集的资产提取结果），不是单集操作；请在确认要整项目重来后再调用。\n\n剧本已修改但尚未重新确认场次时，提交即同步返回 409 DRAMA_STAGE_PRECONDITION，不会创建任务。更新剧本（PUT /episodes/{episodeId}/script）、AI 润色剧本、手动新建场次、编辑场次正文、合并场次、AI 改写场次都会让场次与剧本失去对齐，需先调用 POST /episodes/{episodeId}/asset-extractions 按最新剧本重新确认场次。注意：重新确认会按最新剧本重新拆分该集场次并归档旧场次 / 分镜 / 视频，手动做的场次编辑会被覆盖；如需改内容，建议改剧本后重新确认，而不是直接改场次（与网页端行为一致）。\n\n计费：按任务内模型调用的实际费用（网关标价，不加价）在任务终态一次性结算——成功扣款，失败不扣，取消按已消耗量扣（含取消时仍在进行的调用，账单在任务实际停止后结算）；金额按分四舍五入；模型由平台统一配置，不可指定。提交时余额需大于 0（团队 Key 看团队钱包，非团队 Key 看企业账户余额），否则返回 402 DRAMA_BALANCE_INSUFFICIENT；结算可能把余额扣成负数，之后的计费任务会被拦截直到充值。结算时若因系统原因扣款失败，账单记为欠费（ARREARS / ARREARS_PARTIAL_CANCELED），由平台自动补扣，不影响继续提交。任务从提交到终态占用一个企业 Key 并发名额（GET /quota 的 concurrentLimit），已满返回 429 DRAMA_CONCURRENCY_LIMIT，稍后重试。可用 GET /bills 查账单。",
  "tags": [
    "剧本"
  ],
  "responses": {
    "200": {
      "description": "项目级重新提取资产",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "taskId": {
                    "type": "string",
                    "description": "任务号。"
                  },
                  "type": {
                    "type": "string",
                    "description": "固定为 PROJECT_REEXTRACT。"
                  },
                  "status": {
                    "type": "string"
                  },
                  "progress": {
                    "nullable": true
                  },
                  "result": {
                    "nullable": true,
                    "description": "SUCCEEDED 后内容以内部重提取服务的实际返回为准，未强类型约定；建议成功后另外调用 GET /episodes/(episodeId)/assets 确认结果。"
                  },
                  "error": {
                    "nullable": true
                  },
                  "cost": {
                    "nullable": true
                  },
                  "createdAt": {
                    "type": "string"
                  },
                  "finishedAt": {
                    "nullable": true
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "taskId": "tk_5Fz4Sa1",
              "type": "PROJECT_REEXTRACT",
              "status": "QUEUED",
              "progress": null,
              "result": null,
              "error": null,
              "cost": null,
              "createdAt": "2026-09-17T09:20:00.000+08:00",
              "finishedAt": null
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "Idempotency-Key",
      "in": "header",
      "required": false,
      "description": "幂等键。",
      "schema": {
        "type": "string"
      }
    },
    {
      "name": "projectId",
      "in": "path",
      "required": true,
      "description": "对外项目号。",
      "schema": {
        "type": "string"
      },
      "example": "pj_2V8rglMqiUk"
    }
  ]
}
```


<a id="group-05"></a>

## 自定义画风

<a id="list-custom-styles"></a>

### GET /styles/custom - 自定义画风列表

Operation ID: `list-custom-styles`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=custom-styles-list-custom-styles) | [Saved web text](web-pages/list-custom-styles.txt)

查询当前用户已通过审核的自定义画风（不分页）。

只返回审核通过（APPROVED）、未删除、已启用的画风；审核中 / 被拒的画风不会出现在这里。

Complete operation specification:

```json
{
  "operationId": "list-custom-styles",
  "summary": "自定义画风列表",
  "description": "查询当前用户已通过审核的自定义画风（不分页）。\n\n只返回审核通过（APPROVED）、未删除、已启用的画风；审核中 / 被拒的画风不会出现在这里。",
  "tags": [
    "自定义画风"
  ],
  "responses": {
    "200": {
      "description": "自定义画风列表",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "array",
                "items": {
                  "type": "object",
                  "properties": {
                    "styleId": {
                      "type": "string",
                      "description": "对外自定义画风号，st_ 前缀。"
                    },
                    "label": {
                      "type": "string",
                      "description": "画风名称。"
                    },
                    "prompt": {
                      "type": "string",
                      "description": "画风提示词，参与生图 prompt 拼装。"
                    },
                    "coverUrl": {
                      "type": "string",
                      "description": "封面图地址。"
                    }
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": [
              {
                "styleId": "st_7Gy5Tb3",
                "label": "赛博水彩",
                "prompt": "cyberpunk watercolor style, neon rim light",
                "coverUrl": "https://cdn.runninghub.cn/custom-style/st7gy5tb3.png"
              }
            ]
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  }
}
```

<a id="create-custom-style"></a>

### POST /styles/custom - 创建自定义画风

Operation ID: `create-custom-style`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=custom-styles-create-custom-style) | [Saved web text](web-pages/create-custom-style.txt)

新建一个自定义画风预设。

新建的画风可能需要经过审核才会出现在 GET /styles/custom 里；具体审核策略以平台配置为准，本 API 不提供查审核状态的字段。

Complete operation specification:

```json
{
  "operationId": "create-custom-style",
  "summary": "创建自定义画风",
  "description": "新建一个自定义画风预设。\n\n新建的画风可能需要经过审核才会出现在 GET /styles/custom 里；具体审核策略以平台配置为准，本 API 不提供查审核状态的字段。",
  "tags": [
    "自定义画风"
  ],
  "responses": {
    "200": {
      "description": "创建自定义画风",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "styleId": {
                    "type": "string",
                    "description": "对外自定义画风号。"
                  },
                  "label": {
                    "type": "string",
                    "description": "画风名称。"
                  },
                  "prompt": {
                    "type": "string",
                    "description": "画风提示词。"
                  },
                  "coverUrl": {
                    "type": "string",
                    "description": "封面图地址。"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "styleId": "st_7Gy5Tb3",
              "label": "赛博水彩",
              "prompt": "cyberpunk watercolor style, neon rim light",
              "coverUrl": "https://cdn.runninghub.cn/custom-style/st7gy5tb3.png"
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "requestBody": {
    "required": true,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "label": {
              "type": "string",
              "description": "画风名称。"
            },
            "prompt": {
              "type": "string",
              "description": "画风提示词。"
            },
            "coverUrl": {
              "type": "string",
              "description": "封面图地址（需先自行上传到可公开访问的存储，本接口不接收文件）。"
            }
          },
          "required": [
            "label",
            "prompt",
            "coverUrl"
          ]
        },
        "example": {
          "label": "赛博水彩",
          "prompt": "cyberpunk watercolor style, neon rim light",
          "coverUrl": "https://cdn.example.com/styles/cyber-watercolor.png"
        }
      }
    }
  }
}
```

<a id="update-custom-style"></a>

### PATCH /styles/custom/{styleId} - 更新自定义画风

Operation ID: `update-custom-style`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=custom-styles-update-custom-style) | [Saved web text](web-pages/update-custom-style.txt)

只更新非空字段。

不属于当前调用方或不存在都返回 404 DRAMA_NOT_FOUND。

Complete operation specification:

```json
{
  "operationId": "update-custom-style",
  "summary": "更新自定义画风",
  "description": "只更新非空字段。\n\n不属于当前调用方或不存在都返回 404 DRAMA_NOT_FOUND。",
  "tags": [
    "自定义画风"
  ],
  "responses": {
    "200": {
      "description": "更新自定义画风",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "styleId": {
                    "type": "string",
                    "description": "对外自定义画风号。"
                  },
                  "label": {
                    "type": "string",
                    "description": "画风名称。"
                  },
                  "prompt": {
                    "type": "string",
                    "description": "画风提示词。"
                  },
                  "coverUrl": {
                    "type": "string",
                    "description": "封面图地址。"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "styleId": "st_7Gy5Tb3",
              "label": "赛博水彩 v2",
              "prompt": "cyberpunk watercolor style, neon rim light",
              "coverUrl": "https://cdn.runninghub.cn/custom-style/st7gy5tb3.png"
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "styleId",
      "in": "path",
      "required": true,
      "description": "对外自定义画风号。",
      "schema": {
        "type": "string"
      },
      "example": "st_7Gy5Tb3"
    }
  ],
  "requestBody": {
    "required": false,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "label": {
              "type": "string",
              "description": "画风名称。"
            },
            "prompt": {
              "type": "string",
              "description": "画风提示词。"
            },
            "coverUrl": {
              "type": "string",
              "description": "封面图地址。"
            }
          }
        },
        "example": {
          "label": "赛博水彩 v2"
        }
      }
    }
  }
}
```

<a id="delete-custom-style"></a>

### DELETE /styles/custom/{styleId} - 删除自定义画风

Operation ID: `delete-custom-style`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=custom-styles-delete-custom-style) | [Saved web text](web-pages/delete-custom-style.txt)

删除一个自定义画风预设。

仍被某个项目引用，或正被某个生成中的镜头引用时，返回 409 DRAMA_OPERATION_NOT_ALLOWED，需先解除引用再删除。

Complete operation specification:

```json
{
  "operationId": "delete-custom-style",
  "summary": "删除自定义画风",
  "description": "删除一个自定义画风预设。\n\n仍被某个项目引用，或正被某个生成中的镜头引用时，返回 409 DRAMA_OPERATION_NOT_ALLOWED，需先解除引用再删除。",
  "tags": [
    "自定义画风"
  ],
  "responses": {
    "200": {
      "description": "删除自定义画风",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "nullable": true
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": null
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "styleId",
      "in": "path",
      "required": true,
      "description": "对外自定义画风号。",
      "schema": {
        "type": "string"
      },
      "example": "st_7Gy5Tb3"
    }
  ]
}
```


<a id="group-06"></a>

## 项目

<a id="create-project"></a>

### POST /projects - 创建项目

Operation ID: `create-project`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=projects-create-project) | [Saved web text](web-pages/create-project.txt)

创建一个新项目，可同时传入剧本文本。

通过本接口创建的项目会打上来源标记（source=OPEN_API），在网页端工作台同样可见。

Complete operation specification:

```json
{
  "operationId": "create-project",
  "summary": "创建项目",
  "description": "创建一个新项目，可同时传入剧本文本。\n\n通过本接口创建的项目会打上来源标记（source=OPEN_API），在网页端工作台同样可见。",
  "tags": [
    "项目"
  ],
  "responses": {
    "200": {
      "description": "创建项目",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "projectId": {
                    "type": "string",
                    "description": "对外项目号，pj_ 前缀。"
                  },
                  "title": {
                    "type": "string",
                    "description": "项目标题。"
                  },
                  "description": {
                    "type": "string",
                    "description": "项目简介。"
                  },
                  "status": {
                    "type": "string",
                    "description": "项目状态，新建时固定为 DRAFT。"
                  },
                  "createdAt": {
                    "type": "string",
                    "description": "ISO-8601 创建时间。"
                  },
                  "updatedAt": {
                    "type": "string",
                    "description": "ISO-8601 最近更新时间。"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "projectId": "pj_2V8rglMqiUk",
              "title": "霓虹都市",
              "description": "赛博朋克短剧",
              "status": "DRAFT",
              "createdAt": "2026-09-16T09:00:00.000+08:00",
              "updatedAt": "2026-09-16T09:00:00.000+08:00"
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "Idempotency-Key",
      "in": "header",
      "required": false,
      "description": "幂等键，按（企业 Key，该值）24 小时内去重；同 key 请求体不同返回 409。",
      "schema": {
        "type": "string"
      },
      "example": "create-project-20260916-0001"
    }
  ],
  "requestBody": {
    "required": true,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "title": {
              "type": "string",
              "description": "项目标题。"
            },
            "description": {
              "type": "string",
              "description": "项目简介。"
            },
            "scriptContent": {
              "type": "string",
              "description": "剧本文本内容，可与 scriptFileName 同时提供。只存在项目上，不会写入任何剧集的剧本：要走提资产 / 分镜，仍需对每集调用 PUT /episodes/{episodeId}/script 写入剧本（或改用 POST /project-imports 自动分集）。"
            },
            "scriptFileName": {
              "type": "string",
              "description": "上传的剧本文件名，仅作展示用途。"
            }
          },
          "required": [
            "title"
          ]
        },
        "example": {
          "title": "霓虹都市",
          "description": "赛博朋克短剧",
          "scriptContent": "第一集\n场景一：雨夜街头……",
          "scriptFileName": "ep01.txt"
        }
      }
    }
  }
}
```

<a id="list-projects"></a>

### GET /projects - 项目列表

Operation ID: `list-projects`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=projects-list-projects) | [Saved web text](web-pages/list-projects.txt)

游标分页查询当前企业 Key 下的项目。

Complete operation specification:

```json
{
  "operationId": "list-projects",
  "summary": "项目列表",
  "description": "游标分页查询当前企业 Key 下的项目。",
  "tags": [
    "项目"
  ],
  "responses": {
    "200": {
      "description": "项目列表",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "items": {
                    "type": "array",
                    "items": {
                      "type": "object",
                      "properties": {
                        "projectId": {
                          "type": "string"
                        },
                        "title": {
                          "type": "string"
                        },
                        "description": {
                          "type": "string"
                        },
                        "status": {
                          "type": "string"
                        },
                        "createdAt": {
                          "type": "string"
                        },
                        "updatedAt": {
                          "type": "string"
                        }
                      }
                    },
                    "description": "本页项目列表，元素结构同「查询项目」的 data。"
                  },
                  "nextCursor": {
                    "nullable": true,
                    "description": "下一页游标；为空表示没有下一页。"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "items": [
                {
                  "projectId": "pj_2V8rglMqiUk",
                  "title": "霓虹都市",
                  "description": "赛博朋克短剧",
                  "status": "DRAFT",
                  "createdAt": "2026-09-16T09:00:00.000+08:00",
                  "updatedAt": "2026-09-16T09:00:00.000+08:00"
                }
              ],
              "nextCursor": null
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "cursor",
      "in": "query",
      "required": false,
      "description": "游标，取上一页响应的 nextCursor；首页不传。",
      "schema": {
        "type": "string"
      }
    },
    {
      "name": "limit",
      "in": "query",
      "required": false,
      "description": "每页条数，1~100，缺省 20，越界返回 422。",
      "schema": {
        "type": "integer"
      },
      "example": "20"
    }
  ]
}
```

<a id="get-project"></a>

### GET /projects/{projectId} - 查询项目

Operation ID: `get-project`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=projects-get-project) | [Saved web text](web-pages/get-project.txt)

按项目号查询详情。

不属于当前企业 Key 或 id 不合法都返回 404 DRAMA_NOT_FOUND，不区分两种情况。

Complete operation specification:

```json
{
  "operationId": "get-project",
  "summary": "查询项目",
  "description": "按项目号查询详情。\n\n不属于当前企业 Key 或 id 不合法都返回 404 DRAMA_NOT_FOUND，不区分两种情况。",
  "tags": [
    "项目"
  ],
  "responses": {
    "200": {
      "description": "查询项目",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "projectId": {
                    "type": "string",
                    "description": "对外项目号。"
                  },
                  "title": {
                    "type": "string",
                    "description": "项目标题。"
                  },
                  "description": {
                    "type": "string",
                    "description": "项目简介。"
                  },
                  "status": {
                    "type": "string",
                    "description": "项目状态。"
                  },
                  "createdAt": {
                    "type": "string",
                    "description": "ISO-8601 创建时间。"
                  },
                  "updatedAt": {
                    "type": "string",
                    "description": "ISO-8601 最近更新时间。"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "projectId": "pj_2V8rglMqiUk",
              "title": "霓虹都市",
              "description": "赛博朋克短剧",
              "status": "DRAFT",
              "createdAt": "2026-09-16T09:00:00.000+08:00",
              "updatedAt": "2026-09-16T09:00:00.000+08:00"
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "projectId",
      "in": "path",
      "required": true,
      "description": "对外项目号。",
      "schema": {
        "type": "string"
      },
      "example": "pj_2V8rglMqiUk"
    }
  ]
}
```

<a id="update-project"></a>

### PATCH /projects/{projectId} - 更新项目

Operation ID: `update-project`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=projects-update-project) | [Saved web text](web-pages/update-project.txt)

修改项目标题 / 简介，字段为空不修改。

Complete operation specification:

```json
{
  "operationId": "update-project",
  "summary": "更新项目",
  "description": "修改项目标题 / 简介，字段为空不修改。",
  "tags": [
    "项目"
  ],
  "responses": {
    "200": {
      "description": "更新项目",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "projectId": {
                    "type": "string",
                    "description": "对外项目号。"
                  },
                  "title": {
                    "type": "string",
                    "description": "项目标题。"
                  },
                  "description": {
                    "type": "string",
                    "description": "项目简介。"
                  },
                  "status": {
                    "type": "string",
                    "description": "项目状态。"
                  },
                  "createdAt": {
                    "type": "string",
                    "description": "ISO-8601 创建时间。"
                  },
                  "updatedAt": {
                    "type": "string",
                    "description": "ISO-8601 最近更新时间。"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "projectId": "pj_2V8rglMqiUk",
              "title": "霓虹都市（重制版）",
              "description": "赛博朋克短剧",
              "status": "DRAFT",
              "createdAt": "2026-09-16T09:00:00.000+08:00",
              "updatedAt": "2026-09-17T08:00:00.000+08:00"
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "projectId",
      "in": "path",
      "required": true,
      "description": "对外项目号。",
      "schema": {
        "type": "string"
      },
      "example": "pj_2V8rglMqiUk"
    }
  ],
  "requestBody": {
    "required": false,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "title": {
              "type": "string",
              "description": "新标题，不传则不改。"
            },
            "description": {
              "type": "string",
              "description": "新简介，不传则不改。"
            }
          }
        },
        "example": {
          "title": "霓虹都市（重制版）"
        }
      }
    }
  }
}
```

<a id="delete-project"></a>

### DELETE /projects/{projectId} - 删除项目

Operation ID: `delete-project`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=projects-delete-project) | [Saved web text](web-pages/delete-project.txt)

软删除一个项目。

软删除，删除后再查询该项目返回 404 DRAMA_NOT_FOUND；请谨慎调用，当前没有恢复接口。

Complete operation specification:

```json
{
  "operationId": "delete-project",
  "summary": "删除项目",
  "description": "软删除一个项目。\n\n软删除，删除后再查询该项目返回 404 DRAMA_NOT_FOUND；请谨慎调用，当前没有恢复接口。",
  "tags": [
    "项目"
  ],
  "responses": {
    "200": {
      "description": "删除项目",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "nullable": true
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": null
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "projectId",
      "in": "path",
      "required": true,
      "description": "对外项目号。",
      "schema": {
        "type": "string"
      },
      "example": "pj_2V8rglMqiUk"
    }
  ]
}
```

<a id="list-project-episodes"></a>

### GET /projects/{projectId}/episodes - 项目剧集列表

Operation ID: `list-project-episodes`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=projects-list-project-episodes) | [Saved web text](web-pages/list-project-episodes.txt)

游标分页查询该项目下的剧集，按剧情顺序排列。

本接口游标是不透明字符串，与其它列表接口的游标格式不通用，只能原样传回本接口。

Complete operation specification:

```json
{
  "operationId": "list-project-episodes",
  "summary": "项目剧集列表",
  "description": "游标分页查询该项目下的剧集，按剧情顺序排列。\n\n本接口游标是不透明字符串，与其它列表接口的游标格式不通用，只能原样传回本接口。",
  "tags": [
    "项目"
  ],
  "responses": {
    "200": {
      "description": "项目剧集列表",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "items": {
                    "type": "array",
                    "items": {
                      "type": "object",
                      "properties": {
                        "episodeId": {
                          "type": "string"
                        },
                        "projectId": {
                          "type": "string"
                        },
                        "title": {
                          "type": "string"
                        },
                        "episodeIndex": {
                          "type": "number"
                        },
                        "status": {
                          "type": "string"
                        },
                        "stylePresetId": {
                          "nullable": true
                        },
                        "createdAt": {
                          "type": "string"
                        }
                      }
                    },
                    "description": "本页剧集列表，元素结构同「查询剧集」的 data。"
                  },
                  "nextCursor": {
                    "nullable": true,
                    "description": "下一页游标；为空表示没有下一页。"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "items": [
                {
                  "episodeId": "ep_4Rt7QxNp1",
                  "projectId": "pj_2V8rglMqiUk",
                  "title": "第一集：雨夜",
                  "episodeIndex": 1,
                  "status": "DRAFT",
                  "stylePresetId": null,
                  "createdAt": "2026-09-16T09:05:00.000+08:00"
                }
              ],
              "nextCursor": null
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "projectId",
      "in": "path",
      "required": true,
      "description": "对外项目号。",
      "schema": {
        "type": "string"
      },
      "example": "pj_2V8rglMqiUk"
    },
    {
      "name": "cursor",
      "in": "query",
      "required": false,
      "description": "游标，取上一页响应的 nextCursor；首页不传。",
      "schema": {
        "type": "string"
      }
    },
    {
      "name": "limit",
      "in": "query",
      "required": false,
      "description": "每页条数，1~100，缺省 20，越界返回 422。",
      "schema": {
        "type": "integer"
      }
    }
  ]
}
```


<a id="group-07"></a>

## 剧集与剧本

<a id="create-episode"></a>

### POST /projects/{projectId}/episodes - 创建剧集

Operation ID: `create-episode`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=episodes-create-episode) | [Saved web text](web-pages/create-episode.txt)

在指定项目下创建一集。

Complete operation specification:

```json
{
  "operationId": "create-episode",
  "summary": "创建剧集",
  "description": "在指定项目下创建一集。",
  "tags": [
    "剧集与剧本"
  ],
  "responses": {
    "200": {
      "description": "创建剧集",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "episodeId": {
                    "type": "string",
                    "description": "对外剧集号，ep_ 前缀。"
                  },
                  "projectId": {
                    "type": "string",
                    "description": "所属项目号。"
                  },
                  "title": {
                    "type": "string",
                    "description": "剧集标题。"
                  },
                  "episodeIndex": {
                    "type": "number",
                    "description": "集数序号，从 1 开始。"
                  },
                  "status": {
                    "type": "string",
                    "description": "剧集状态：DRAFT（生产未完成）或 COMPLETED（整集视频已导出）。",
                    "enum": [
                      "DRAFT",
                      "COMPLETED"
                    ]
                  },
                  "stylePresetId": {
                    "nullable": true,
                    "description": "画风预设 id（GET /catalog/styles），由 asset-extractions 时传入的值写入；尚未提取资产时为 null。"
                  },
                  "createdAt": {
                    "type": "string",
                    "description": "ISO-8601 创建时间。"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "episodeId": "ep_4Rt7QxNp1",
              "projectId": "pj_2V8rglMqiUk",
              "title": "第一集：雨夜",
              "episodeIndex": 1,
              "status": "DRAFT",
              "stylePresetId": null,
              "createdAt": "2026-09-16T09:05:00.000+08:00"
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "Idempotency-Key",
      "in": "header",
      "required": false,
      "description": "幂等键，同「创建项目」。",
      "schema": {
        "type": "string"
      }
    },
    {
      "name": "projectId",
      "in": "path",
      "required": true,
      "description": "所属项目号。",
      "schema": {
        "type": "string"
      },
      "example": "pj_2V8rglMqiUk"
    }
  ],
  "requestBody": {
    "required": true,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "title": {
              "type": "string",
              "description": "剧集标题。"
            }
          },
          "required": [
            "title"
          ]
        },
        "example": {
          "title": "第一集：雨夜"
        }
      }
    }
  }
}
```

<a id="get-episode"></a>

### GET /episodes/{episodeId} - 查询剧集

Operation ID: `get-episode`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=episodes-get-episode) | [Saved web text](web-pages/get-episode.txt)

按剧集号查询详情。

Complete operation specification:

```json
{
  "operationId": "get-episode",
  "summary": "查询剧集",
  "description": "按剧集号查询详情。",
  "tags": [
    "剧集与剧本"
  ],
  "responses": {
    "200": {
      "description": "查询剧集",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "episodeId": {
                    "type": "string",
                    "description": "对外剧集号。"
                  },
                  "projectId": {
                    "type": "string",
                    "description": "所属项目号。"
                  },
                  "title": {
                    "type": "string",
                    "description": "剧集标题。"
                  },
                  "episodeIndex": {
                    "type": "number",
                    "description": "集数序号。"
                  },
                  "status": {
                    "type": "string",
                    "description": "剧集状态。",
                    "enum": [
                      "DRAFT",
                      "COMPLETED"
                    ]
                  },
                  "stylePresetId": {
                    "nullable": true,
                    "description": "画风预设 id（GET /catalog/styles），由 asset-extractions 时传入的值写入；尚未提取资产时为 null。"
                  },
                  "createdAt": {
                    "type": "string",
                    "description": "ISO-8601 创建时间。"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "episodeId": "ep_4Rt7QxNp1",
              "projectId": "pj_2V8rglMqiUk",
              "title": "第一集：雨夜",
              "episodeIndex": 1,
              "status": "DRAFT",
              "stylePresetId": null,
              "createdAt": "2026-09-16T09:05:00.000+08:00"
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "episodeId",
      "in": "path",
      "required": true,
      "description": "对外剧集号。",
      "schema": {
        "type": "string"
      },
      "example": "ep_4Rt7QxNp1"
    }
  ]
}
```

<a id="update-episode"></a>

### PATCH /episodes/{episodeId} - 更新剧集

Operation ID: `update-episode`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=episodes-update-episode) | [Saved web text](web-pages/update-episode.txt)

修改剧集标题，字段为空不修改。

Complete operation specification:

```json
{
  "operationId": "update-episode",
  "summary": "更新剧集",
  "description": "修改剧集标题，字段为空不修改。",
  "tags": [
    "剧集与剧本"
  ],
  "responses": {
    "200": {
      "description": "更新剧集",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "episodeId": {
                    "type": "string",
                    "description": "对外剧集号。"
                  },
                  "projectId": {
                    "type": "string",
                    "description": "所属项目号。"
                  },
                  "title": {
                    "type": "string",
                    "description": "剧集标题。"
                  },
                  "episodeIndex": {
                    "type": "number",
                    "description": "集数序号。"
                  },
                  "status": {
                    "type": "string",
                    "description": "剧集状态。",
                    "enum": [
                      "DRAFT",
                      "COMPLETED"
                    ]
                  },
                  "stylePresetId": {
                    "nullable": true,
                    "description": "画风预设 id。"
                  },
                  "createdAt": {
                    "type": "string",
                    "description": "ISO-8601 创建时间。"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "episodeId": "ep_4Rt7QxNp1",
              "projectId": "pj_2V8rglMqiUk",
              "title": "第一集：雨夜（修订）",
              "episodeIndex": 1,
              "status": "DRAFT",
              "stylePresetId": null,
              "createdAt": "2026-09-16T09:05:00.000+08:00"
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "episodeId",
      "in": "path",
      "required": true,
      "description": "对外剧集号。",
      "schema": {
        "type": "string"
      },
      "example": "ep_4Rt7QxNp1"
    }
  ],
  "requestBody": {
    "required": false,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "title": {
              "type": "string",
              "description": "新标题，不传则不改。"
            }
          }
        },
        "example": {
          "title": "第一集：雨夜（修订）"
        }
      }
    }
  }
}
```

<a id="delete-episode"></a>

### DELETE /episodes/{episodeId} - 删除剧集

Operation ID: `delete-episode`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=episodes-delete-episode) | [Saved web text](web-pages/delete-episode.txt)

软删除一集。

软删除，删除后再查询该集返回 404 DRAMA_NOT_FOUND；请谨慎调用，当前没有恢复接口。

部分内部工具生成的特殊剧集不可删除，此时返回 400 DRAMA_REQUEST_FAILED，message 说明该剧集不可删除。

Complete operation specification:

```json
{
  "operationId": "delete-episode",
  "summary": "删除剧集",
  "description": "软删除一集。\n\n软删除，删除后再查询该集返回 404 DRAMA_NOT_FOUND；请谨慎调用，当前没有恢复接口。\n\n部分内部工具生成的特殊剧集不可删除，此时返回 400 DRAMA_REQUEST_FAILED，message 说明该剧集不可删除。",
  "tags": [
    "剧集与剧本"
  ],
  "responses": {
    "200": {
      "description": "删除剧集",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "nullable": true
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": null
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "episodeId",
      "in": "path",
      "required": true,
      "description": "对外剧集号。",
      "schema": {
        "type": "string"
      },
      "example": "ep_4Rt7QxNp1"
    }
  ]
}
```

<a id="update-script"></a>

### PUT /episodes/{episodeId}/script - 更新剧本

Operation ID: `update-script`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=episodes-update-script) | [Saved web text](web-pages/update-script.txt)

更新该集的剧本文本，落一份新快照。

本接口不支持 Idempotency-Key（不是新建资源的操作）；内容与最新快照相同时直接复用、不新增版本。存入前会去掉 markdown 标题前缀，存入内容可能与提交文本略有差异。

保存剧本不触发任何模型调用、不计费。

发起 asset-extractions 之前必须先调用本接口至少一次，否则返回 422 DRAMA_STAGE_INPUT_EMPTY。

Complete operation specification:

```json
{
  "operationId": "update-script",
  "summary": "更新剧本",
  "description": "更新该集的剧本文本，落一份新快照。\n\n本接口不支持 Idempotency-Key（不是新建资源的操作）；内容与最新快照相同时直接复用、不新增版本。存入前会去掉 markdown 标题前缀，存入内容可能与提交文本略有差异。\n\n保存剧本不触发任何模型调用、不计费。\n\n发起 asset-extractions 之前必须先调用本接口至少一次，否则返回 422 DRAMA_STAGE_INPUT_EMPTY。",
  "tags": [
    "剧集与剧本"
  ],
  "responses": {
    "200": {
      "description": "更新剧本",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "episodeId": {
                    "type": "string",
                    "description": "对外剧集号。"
                  },
                  "projectId": {
                    "type": "string",
                    "description": "所属项目号。"
                  },
                  "title": {
                    "type": "string",
                    "description": "剧集标题。"
                  },
                  "episodeIndex": {
                    "type": "number",
                    "description": "集数序号。"
                  },
                  "status": {
                    "type": "string",
                    "description": "剧集状态。",
                    "enum": [
                      "DRAFT",
                      "COMPLETED"
                    ]
                  },
                  "stylePresetId": {
                    "nullable": true,
                    "description": "画风预设 id（GET /catalog/styles），由 asset-extractions 时传入的值写入；尚未提取资产时为 null。"
                  },
                  "createdAt": {
                    "type": "string",
                    "description": "ISO-8601 创建时间。"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "episodeId": "ep_4Rt7QxNp1",
              "projectId": "pj_2V8rglMqiUk",
              "title": "第一集：雨夜",
              "episodeIndex": 1,
              "status": "DRAFT",
              "stylePresetId": null,
              "createdAt": "2026-09-16T09:05:00.000+08:00"
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "episodeId",
      "in": "path",
      "required": true,
      "description": "对外剧集号。",
      "schema": {
        "type": "string"
      },
      "example": "ep_4Rt7QxNp1"
    }
  ],
  "requestBody": {
    "required": true,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "scriptContent": {
              "type": "string",
              "description": "剧本文本内容。"
            },
            "scriptFileName": {
              "type": "string",
              "description": "剧本文件名，项目级字段，传了才会更新。"
            }
          },
          "required": [
            "scriptContent"
          ]
        },
        "example": {
          "scriptContent": "第一集\n场景一：雨夜街头……（修订版）",
          "scriptFileName": "ep01_v2.txt"
        }
      }
    }
  }
}
```

<a id="get-episode-settings"></a>

### GET /episodes/{episodeId}/settings - 查询剧集设置

Operation ID: `get-episode-settings`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=episodes-get-episode-settings) | [Saved web text](web-pages/get-episode-settings.txt)

查询画幅取向、分镜导演风格、时长模式、镜头节奏、故事板图渠道。

Complete operation specification:

```json
{
  "operationId": "get-episode-settings",
  "summary": "查询剧集设置",
  "description": "查询画幅取向、分镜导演风格、时长模式、镜头节奏、故事板图渠道。",
  "tags": [
    "剧集与剧本"
  ],
  "responses": {
    "200": {
      "description": "查询剧集设置",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "orientation": {
                    "type": "string",
                    "description": "画幅取向。",
                    "enum": [
                      "LANDSCAPE",
                      "PORTRAIT"
                    ]
                  },
                  "directorStyleKey": {
                    "type": "string",
                    "description": "内置分镜导演风格 key（GET /catalog/director-styles 的 key），未设置为 null。"
                  },
                  "durationMode": {
                    "type": "string",
                    "description": "分镜时长模式。",
                    "enum": [
                      "standard",
                      "adaptive"
                    ]
                  },
                  "pacingMode": {
                    "nullable": true,
                    "description": "分镜镜头节奏，未设置为 null（自动规划）。"
                  },
                  "storyboardImageApp": {
                    "nullable": true,
                    "description": "故事板图渠道内部应用 id 的原样字符串（配置项，非用户资源，不是 OpenIds 编码），未设置为 null。"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "orientation": "LANDSCAPE",
              "directorStyleKey": "CINEMATIC_WIDE",
              "durationMode": "standard",
              "pacingMode": null,
              "storyboardImageApp": null
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "episodeId",
      "in": "path",
      "required": true,
      "description": "对外剧集号。",
      "schema": {
        "type": "string"
      },
      "example": "ep_4Rt7QxNp1"
    }
  ]
}
```

<a id="update-episode-settings"></a>

### PUT /episodes/{episodeId}/settings - 更新剧集设置

Operation ID: `update-episode-settings`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=episodes-update-episode-settings) | [Saved web text](web-pages/update-episode-settings.txt)

更新画幅取向、分镜导演风格、时长模式、镜头节奏、故事板图渠道，字段为空不修改。

directorStyleKey、durationMode、pacingMode 落在同一条内部配置上，只提交其中部分字段时其余沿用当前已保存的值，不会被顺带清空。

pacingMode 传入不支持的值返回 422 DRAMA_VALIDATION_FAILED。

storyboardImageApp 传入非数字字符串会返回 400 DRAMA_REQUEST_FAILED。

Complete operation specification:

```json
{
  "operationId": "update-episode-settings",
  "summary": "更新剧集设置",
  "description": "更新画幅取向、分镜导演风格、时长模式、镜头节奏、故事板图渠道，字段为空不修改。\n\ndirectorStyleKey、durationMode、pacingMode 落在同一条内部配置上，只提交其中部分字段时其余沿用当前已保存的值，不会被顺带清空。\n\npacingMode 传入不支持的值返回 422 DRAMA_VALIDATION_FAILED。\n\nstoryboardImageApp 传入非数字字符串会返回 400 DRAMA_REQUEST_FAILED。",
  "tags": [
    "剧集与剧本"
  ],
  "responses": {
    "200": {
      "description": "更新剧集设置",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "orientation": {
                    "type": "string",
                    "description": "画幅取向。",
                    "enum": [
                      "LANDSCAPE",
                      "PORTRAIT"
                    ]
                  },
                  "directorStyleKey": {
                    "type": "string",
                    "description": "内置分镜导演风格 key，未设置为 null。"
                  },
                  "durationMode": {
                    "type": "string",
                    "description": "分镜时长模式。",
                    "enum": [
                      "standard",
                      "adaptive"
                    ]
                  },
                  "pacingMode": {
                    "type": "string",
                    "description": "分镜镜头节奏，未设置为 null（自动规划）。",
                    "enum": [
                      "compact",
                      "balanced",
                      "relaxed"
                    ]
                  },
                  "storyboardImageApp": {
                    "nullable": true,
                    "description": "故事板图渠道内部应用 id 的原样字符串，未设置为 null。"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "orientation": "PORTRAIT",
              "directorStyleKey": "CINEMATIC_WIDE",
              "durationMode": "standard",
              "pacingMode": "compact",
              "storyboardImageApp": null
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "episodeId",
      "in": "path",
      "required": true,
      "description": "对外剧集号。",
      "schema": {
        "type": "string"
      },
      "example": "ep_4Rt7QxNp1"
    }
  ],
  "requestBody": {
    "required": false,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "orientation": {
              "type": "string",
              "enum": [
                "LANDSCAPE",
                "PORTRAIT"
              ],
              "description": "画幅取向，不传则不改；非法值返回 422 DRAMA_VALIDATION_FAILED。"
            },
            "directorStyleKey": {
              "type": "string",
              "description": "内置分镜导演风格 key（GET /catalog/director-styles 的 key），不传则不改；设置后会清空该集已保存的自定义导演风格文档。"
            },
            "durationMode": {
              "type": "string",
              "enum": [
                "standard",
                "adaptive"
              ],
              "description": "分镜时长模式，不传则不改；非法值返回 422 DRAMA_VALIDATION_FAILED。"
            },
            "pacingMode": {
              "type": "string",
              "enum": [
                "compact",
                "balanced",
                "relaxed"
              ],
              "description": "分镜镜头节奏：compact 紧凑（约 1.5–3.5 秒一镜）、balanced 适中、relaxed 舒缓（约 2.5–4.5 秒一镜）；不传则不改，传空字符串清除（自动规划）。对之后生成的分镜生效。"
            },
            "storyboardImageApp": {
              "type": "string",
              "description": "故事板图渠道内部应用 id 的原样字符串，不传则不改；传空字符串表示恢复默认渠道。该设置只影响网页工作台的分镜生图；开放 API 的 image-generations 以请求里的 appCode 为准。"
            }
          }
        },
        "example": {
          "orientation": "PORTRAIT",
          "directorStyleKey": "CINEMATIC_WIDE",
          "pacingMode": "compact"
        }
      }
    }
  }
}
```


<a id="group-08"></a>

## 资产

<a id="extract-assets"></a>

### POST /episodes/{episodeId}/asset-extractions - 提取资产

Operation ID: `extract-assets`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=assets-extract-assets) | [Saved web text](web-pages/extract-assets.txt)

用 LLM 从剧本中提取角色 / 场景 / 道具资产，异步任务。

前置条件：该集必须已通过 PUT /episodes/{episodeId}/script 写入过剧本，否则 422 DRAMA_STAGE_INPUT_EMPTY。

作用范围：首次提取为项目级，对整本剧本一次完成场次拆分与资产提取、覆盖全部剧集（与网页端「确认剧本」一致）；项目已有已发布的资产基线后，再次调用只确认并提取 episodeId 这一集。同一项目同一时间只允许一个提取任务，另一集提取进行中时返回 409 DRAMA_OPERATION_NOT_ALLOWED。

若该集剧本已修改（如更新过剧本、调用过 AI 润色剧本 / 编辑过场次正文），本接口会按最新剧本重新确认场次，等同网页端「确认剧本」：该集旧的场次、分镜、镜头视频会被归档并重建，手动做的场次编辑会被覆盖。若项目内其他集的剧本也已修改但未确认，返回 409 DRAMA_STAGE_PRECONDITION，message 会指出是哪一集。

storyboards / shot-rebuilds 等阶段接口不接收请求体；asset-extractions 可选传 stylePresetId。使用的模型由平台按阶段统一配置，与网页端效果一致。

stylePresetId 传了但查无记录或已删除，返回 422 DRAMA_STYLE_NOT_FOUND。

计费：按任务内模型调用的实际费用（网关标价，不加价）在任务终态一次性结算——成功扣款，失败不扣，取消按已消耗量扣（含取消时仍在进行的调用，账单在任务实际停止后结算）；金额按分四舍五入；模型由平台统一配置，不可指定。提交时余额需大于 0（团队 Key 看团队钱包，非团队 Key 看企业账户余额），否则返回 402 DRAMA_BALANCE_INSUFFICIENT；结算可能把余额扣成负数，之后的计费任务会被拦截直到充值。结算时若因系统原因扣款失败，账单记为欠费（ARREARS / ARREARS_PARTIAL_CANCELED），由平台自动补扣，不影响继续提交。任务从提交到终态占用一个企业 Key 并发名额（GET /quota 的 concurrentLimit），已满返回 429 DRAMA_CONCURRENCY_LIMIT，稍后重试。可用 GET /bills 查账单。

Complete operation specification:

```json
{
  "operationId": "extract-assets",
  "summary": "提取资产",
  "description": "用 LLM 从剧本中提取角色 / 场景 / 道具资产，异步任务。\n\n前置条件：该集必须已通过 PUT /episodes/{episodeId}/script 写入过剧本，否则 422 DRAMA_STAGE_INPUT_EMPTY。\n\n作用范围：首次提取为项目级，对整本剧本一次完成场次拆分与资产提取、覆盖全部剧集（与网页端「确认剧本」一致）；项目已有已发布的资产基线后，再次调用只确认并提取 episodeId 这一集。同一项目同一时间只允许一个提取任务，另一集提取进行中时返回 409 DRAMA_OPERATION_NOT_ALLOWED。\n\n若该集剧本已修改（如更新过剧本、调用过 AI 润色剧本 / 编辑过场次正文），本接口会按最新剧本重新确认场次，等同网页端「确认剧本」：该集旧的场次、分镜、镜头视频会被归档并重建，手动做的场次编辑会被覆盖。若项目内其他集的剧本也已修改但未确认，返回 409 DRAMA_STAGE_PRECONDITION，message 会指出是哪一集。\n\nstoryboards / shot-rebuilds 等阶段接口不接收请求体；asset-extractions 可选传 stylePresetId。使用的模型由平台按阶段统一配置，与网页端效果一致。\n\nstylePresetId 传了但查无记录或已删除，返回 422 DRAMA_STYLE_NOT_FOUND。\n\n计费：按任务内模型调用的实际费用（网关标价，不加价）在任务终态一次性结算——成功扣款，失败不扣，取消按已消耗量扣（含取消时仍在进行的调用，账单在任务实际停止后结算）；金额按分四舍五入；模型由平台统一配置，不可指定。提交时余额需大于 0（团队 Key 看团队钱包，非团队 Key 看企业账户余额），否则返回 402 DRAMA_BALANCE_INSUFFICIENT；结算可能把余额扣成负数，之后的计费任务会被拦截直到充值。结算时若因系统原因扣款失败，账单记为欠费（ARREARS / ARREARS_PARTIAL_CANCELED），由平台自动补扣，不影响继续提交。任务从提交到终态占用一个企业 Key 并发名额（GET /quota 的 concurrentLimit），已满返回 429 DRAMA_CONCURRENCY_LIMIT，稍后重试。可用 GET /bills 查账单。",
  "tags": [
    "资产"
  ],
  "responses": {
    "200": {
      "description": "提取资产",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "taskId": {
                    "type": "string",
                    "description": "任务号，用于轮询 GET /tasks/{taskNo}。"
                  },
                  "type": {
                    "type": "string",
                    "description": "固定为 ASSET_EXTRACT。"
                  },
                  "status": {
                    "type": "string",
                    "description": "提交时固定为 QUEUED。"
                  },
                  "progress": {
                    "nullable": true
                  },
                  "result": {
                    "nullable": true,
                    "description": "提交时为 null；SUCCEEDED 后内容为本次提取到的资产统计等信息。"
                  },
                  "error": {
                    "nullable": true,
                    "description": "提交时为 null。"
                  },
                  "cost": {
                    "nullable": true
                  },
                  "createdAt": {
                    "type": "string",
                    "description": "ISO-8601 创建时间。"
                  },
                  "finishedAt": {
                    "nullable": true,
                    "description": "提交时为 null。"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "taskId": "tk_1Xh6Bs4Q",
              "type": "ASSET_EXTRACT",
              "status": "QUEUED",
              "progress": null,
              "result": null,
              "error": null,
              "cost": null,
              "createdAt": "2026-09-16T09:10:00.000+08:00",
              "finishedAt": null
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "Idempotency-Key",
      "in": "header",
      "required": false,
      "description": "幂等键，24 小时内按（企业 Key，该值）去重。",
      "schema": {
        "type": "string"
      },
      "example": "extract-ep4rt7-20260916"
    },
    {
      "name": "episodeId",
      "in": "path",
      "required": true,
      "description": "对外剧集号。",
      "schema": {
        "type": "string"
      },
      "example": "ep_4Rt7QxNp1"
    }
  ],
  "requestBody": {
    "required": false,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "stylePresetId": {
              "type": "string",
              "description": "画风预设 id，取自 GET /catalog/styles；不传沿用剧集已有画风。"
            }
          }
        },
        "example": {
          "stylePresetId": "88123"
        }
      }
    }
  }
}
```

<a id="list-assets"></a>

### GET /episodes/{episodeId}/assets - 资产列表

Operation ID: `list-assets`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=assets-list-assets) | [Saved web text](web-pages/list-assets.txt)

游标分页查询该集下的资产。

Complete operation specification:

```json
{
  "operationId": "list-assets",
  "summary": "资产列表",
  "description": "游标分页查询该集下的资产。",
  "tags": [
    "资产"
  ],
  "responses": {
    "200": {
      "description": "资产列表",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "items": {
                    "type": "array",
                    "items": {
                      "type": "object",
                      "properties": {
                        "assetId": {
                          "type": "string"
                        },
                        "name": {
                          "type": "string"
                        },
                        "type": {
                          "type": "string"
                        },
                        "description": {
                          "type": "string"
                        },
                        "imageUrl": {
                          "type": "string"
                        },
                        "createdAt": {
                          "type": "string"
                        }
                      }
                    }
                  },
                  "nextCursor": {
                    "nullable": true
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "items": [
                {
                  "assetId": "as_5Ln9Vt2",
                  "name": "林夏",
                  "type": "CHARACTER",
                  "description": "女主角，25岁，短发",
                  "imageUrl": "https://cos.runninghub.cn/aivideo/asset/xxx.png?sign=...",
                  "createdAt": "2026-09-16T09:12:00.000+08:00"
                }
              ],
              "nextCursor": null
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "episodeId",
      "in": "path",
      "required": true,
      "description": "对外剧集号。",
      "schema": {
        "type": "string"
      },
      "example": "ep_4Rt7QxNp1"
    },
    {
      "name": "cursor",
      "in": "query",
      "required": false,
      "description": "游标，取上一页响应的 nextCursor。",
      "schema": {
        "type": "string"
      }
    },
    {
      "name": "limit",
      "in": "query",
      "required": false,
      "description": "每页条数，1~100，缺省 20，越界返回 422。",
      "schema": {
        "type": "integer"
      }
    }
  ]
}
```

<a id="create-asset"></a>

### POST /episodes/{episodeId}/assets - 创建资产

Operation ID: `create-asset`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=assets-create-asset) | [Saved web text](web-pages/create-asset.txt)

在指定剧集下手动创建一个资产（角色 / 场景 / 道具）。

不支持 Idempotency-Key，重复提交会创建多个同名资产。

Complete operation specification:

```json
{
  "operationId": "create-asset",
  "summary": "创建资产",
  "description": "在指定剧集下手动创建一个资产（角色 / 场景 / 道具）。\n\n不支持 Idempotency-Key，重复提交会创建多个同名资产。",
  "tags": [
    "资产"
  ],
  "responses": {
    "200": {
      "description": "创建资产",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "assetId": {
                    "type": "string",
                    "description": "对外资产号。"
                  },
                  "name": {
                    "type": "string",
                    "description": "资产名称。"
                  },
                  "type": {
                    "type": "string",
                    "description": "资产类型。",
                    "enum": [
                      "CHARACTER",
                      "SCENE",
                      "PROP"
                    ]
                  },
                  "description": {
                    "type": "string",
                    "description": "资产描述。"
                  },
                  "imageUrl": {
                    "nullable": true,
                    "description": "刚创建时没有任何变体图片，恒为 null。"
                  },
                  "createdAt": {
                    "type": "string",
                    "description": "ISO-8601 创建时间。"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "assetId": "as_6Mp3Rs1",
              "name": "林夏",
              "type": "CHARACTER",
              "description": "女主角，25岁，短发",
              "imageUrl": null,
              "createdAt": "2026-09-17T09:15:00.000+08:00"
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "episodeId",
      "in": "path",
      "required": true,
      "description": "对外剧集号。",
      "schema": {
        "type": "string"
      },
      "example": "ep_4Rt7QxNp1"
    }
  ],
  "requestBody": {
    "required": true,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "name": {
              "type": "string",
              "description": "资产名称。"
            },
            "type": {
              "type": "string",
              "enum": [
                "CHARACTER",
                "SCENE",
                "PROP"
              ],
              "description": "资产类型；非法值返回 422。"
            },
            "description": {
              "type": "string",
              "description": "资产描述，可空。"
            }
          },
          "required": [
            "name",
            "type"
          ]
        },
        "example": {
          "name": "林夏",
          "type": "CHARACTER",
          "description": "女主角，25岁，短发"
        }
      }
    }
  }
}
```

<a id="generate-asset-image"></a>

### POST /assets/{assetId}/image-generations - 资产生图

Operation ID: `generate-asset-image`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=assets-generate-asset-image) | [Saved web text](web-pages/generate-asset-image.txt)

为指定资产生成形象图，异步任务。

版式由后端按资产类型自动选择（场景走平面图、角色走三视图、道具无版式概念），当前不支持客户端指定单人像 / 全景等版式。

生图费用按 openapi 现有计价结算，不经过 LLM 阶段的账单器，不会出现在 GET /bills 里。

Complete operation specification:

```json
{
  "operationId": "generate-asset-image",
  "summary": "资产生图",
  "description": "为指定资产生成形象图，异步任务。\n\n版式由后端按资产类型自动选择（场景走平面图、角色走三视图、道具无版式概念），当前不支持客户端指定单人像 / 全景等版式。\n\n生图费用按 openapi 现有计价结算，不经过 LLM 阶段的账单器，不会出现在 GET /bills 里。",
  "tags": [
    "资产"
  ],
  "responses": {
    "200": {
      "description": "资产生图",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "taskId": {
                    "type": "string",
                    "description": "任务号。"
                  },
                  "type": {
                    "type": "string",
                    "description": "固定为 ASSET_IMAGE_GENERATE。"
                  },
                  "status": {
                    "type": "string",
                    "description": "提交时固定为 QUEUED。"
                  },
                  "progress": {
                    "nullable": true
                  },
                  "result": {
                    "nullable": true,
                    "description": "SUCCEEDED 后为 { imageUrl }。"
                  },
                  "error": {
                    "nullable": true
                  },
                  "cost": {
                    "nullable": true
                  },
                  "createdAt": {
                    "type": "string"
                  },
                  "finishedAt": {
                    "nullable": true
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "taskId": "tk_4Vm2Ln8",
              "type": "ASSET_IMAGE_GENERATE",
              "status": "QUEUED",
              "progress": null,
              "result": null,
              "error": null,
              "cost": null,
              "createdAt": "2026-09-16T09:15:00.000+08:00",
              "finishedAt": null
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "Idempotency-Key",
      "in": "header",
      "required": false,
      "description": "幂等键。",
      "schema": {
        "type": "string"
      }
    },
    {
      "name": "assetId",
      "in": "path",
      "required": true,
      "description": "对外资产号。",
      "schema": {
        "type": "string"
      },
      "example": "as_5Ln9Vt2"
    }
  ],
  "requestBody": {
    "required": true,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "appCode": {
              "type": "string",
              "description": "生图应用码，取自 GET /catalog/apps（capability=IMAGE）。资产首图没有参考图，建议用 NANO 系列 T2I（如 NANO_PRO_G2_T2I_OFFICIAL）；已有参考图的资产用对应 I2I。appCode 区分大小写；部分第三方应用对空 prompt / 画幅参数校验严格，此时任务以 FAILED 结束，error.code 为 DRAMA_REQUEST_FAILED，上游原始错误码与信息附在 error.message 中。"
            },
            "prompt": {
              "type": "string",
              "description": "自定义提示词；不传则用后端默认拼装逻辑。"
            },
            "aspectRatio": {
              "type": "string",
              "description": "画幅比例，如 16:9；应用不支持时回落默认档。"
            },
            "resolution": {
              "type": "string",
              "description": "分辨率；应用不支持时回落默认档。"
            }
          },
          "required": [
            "appCode"
          ]
        },
        "example": {
          "appCode": "NANO_PRO_G2_T2I_OFFICIAL",
          "prompt": "",
          "aspectRatio": "3:4"
        }
      }
    }
  }
}
```

<a id="get-asset-detail"></a>

### GET /assets/{assetId} - 查询资产详情

Operation ID: `get-asset-detail`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=assets-get-asset-detail) | [Saved web text](web-pages/get-asset-detail.txt)

按资产号查询详情，含变体摘要与出场场次。

不属于当前企业 Key 或 id 不合法都返回 404 DRAMA_NOT_FOUND。

Complete operation specification:

```json
{
  "operationId": "get-asset-detail",
  "summary": "查询资产详情",
  "description": "按资产号查询详情，含变体摘要与出场场次。\n\n不属于当前企业 Key 或 id 不合法都返回 404 DRAMA_NOT_FOUND。",
  "tags": [
    "资产"
  ],
  "responses": {
    "200": {
      "description": "查询资产详情",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "assetId": {
                    "type": "string",
                    "description": "对外资产号。"
                  },
                  "name": {
                    "type": "string",
                    "description": "资产名称。"
                  },
                  "type": {
                    "type": "string",
                    "description": "资产类型。",
                    "enum": [
                      "CHARACTER",
                      "SCENE",
                      "PROP"
                    ]
                  },
                  "description": {
                    "type": "string",
                    "description": "资产描述。"
                  },
                  "imageUrl": {
                    "type": "string",
                    "description": "当前默认变体展示图的可访问地址，取不到默认图时回退第一张非空展示图，未生图则为 null。"
                  },
                  "variants": {
                    "type": "array",
                    "items": {
                      "type": "object",
                      "properties": {
                        "variantId": {
                          "type": "string"
                        },
                        "kind": {
                          "type": "string"
                        },
                        "name": {
                          "type": "string"
                        },
                        "description": {
                          "type": "string"
                        },
                        "imageUrl": {
                          "type": "string"
                        },
                        "isDefault": {
                          "type": "boolean"
                        },
                        "sortOrder": {
                          "type": "number"
                        }
                      }
                    },
                    "description": "变体摘要列表，字段同「变体列表」接口。"
                  },
                  "appearingSceneIds": {
                    "type": "array",
                    "items": {
                      "type": "string"
                    },
                    "description": "出场场次号列表（SCENE / PROP 资产才有意义，角色资产恒为空数组）。"
                  },
                  "createdAt": {
                    "type": "string",
                    "description": "ISO-8601 创建时间。"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "assetId": "as_5Ln9Vt2",
              "name": "林夏",
              "type": "CHARACTER",
              "description": "女主角，25岁，短发",
              "imageUrl": "https://cos.runninghub.cn/aivideo/asset/xxx.png?sign=...",
              "variants": [
                {
                  "variantId": "vr_7Nq4Su2",
                  "kind": "OUTFIT",
                  "name": "日常装",
                  "description": "白色衬衫，牛仔裤",
                  "imageUrl": "https://cos.runninghub.cn/aivideo/asset-variant/xxx.png?sign=...",
                  "isDefault": true,
                  "sortOrder": 0
                }
              ],
              "appearingSceneIds": [
                "sc_6Ym2Wq9"
              ],
              "createdAt": "2026-09-16T09:12:00.000+08:00"
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "assetId",
      "in": "path",
      "required": true,
      "description": "对外资产号。",
      "schema": {
        "type": "string"
      },
      "example": "as_5Ln9Vt2"
    }
  ]
}
```

<a id="update-asset"></a>

### PATCH /assets/{assetId} - 更新资产

Operation ID: `update-asset`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=assets-update-asset) | [Saved web text](web-pages/update-asset.txt)

修改资产名称 / 描述，字段为空不修改。

Complete operation specification:

```json
{
  "operationId": "update-asset",
  "summary": "更新资产",
  "description": "修改资产名称 / 描述，字段为空不修改。",
  "tags": [
    "资产"
  ],
  "responses": {
    "200": {
      "description": "更新资产",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "assetId": {
                    "type": "string",
                    "description": "对外资产号。"
                  },
                  "name": {
                    "type": "string",
                    "description": "资产名称。"
                  },
                  "type": {
                    "type": "string",
                    "description": "资产类型。",
                    "enum": [
                      "CHARACTER",
                      "SCENE",
                      "PROP"
                    ]
                  },
                  "description": {
                    "type": "string",
                    "description": "资产描述。"
                  },
                  "imageUrl": {
                    "type": "string",
                    "description": "当前默认展示图地址。"
                  },
                  "createdAt": {
                    "type": "string",
                    "description": "ISO-8601 创建时间。"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "assetId": "as_5Ln9Vt2",
              "name": "林夏",
              "type": "CHARACTER",
              "description": "女主角，25岁，短发，换季后改留长发",
              "imageUrl": "https://cos.runninghub.cn/aivideo/asset/xxx.png?sign=...",
              "createdAt": "2026-09-16T09:12:00.000+08:00"
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "assetId",
      "in": "path",
      "required": true,
      "description": "对外资产号。",
      "schema": {
        "type": "string"
      },
      "example": "as_5Ln9Vt2"
    }
  ],
  "requestBody": {
    "required": false,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "name": {
              "type": "string",
              "description": "新名称，不传则不改。"
            },
            "description": {
              "type": "string",
              "description": "新描述，不传则不改。"
            }
          }
        },
        "example": {
          "description": "女主角，25岁，短发，换季后改留长发"
        }
      }
    }
  }
}
```

<a id="delete-asset"></a>

### DELETE /assets/{assetId} - 删除资产

Operation ID: `delete-asset`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=assets-delete-asset) | [Saved web text](web-pages/delete-asset.txt)

删除资产整体，或只解除它与某一集的关联。

entire=true 会真正删除资产本体（含全部变体与历史图片），已经绑定该资产的镜头 / 场次会一并解除绑定，请谨慎调用。

Complete operation specification:

```json
{
  "operationId": "delete-asset",
  "summary": "删除资产",
  "description": "删除资产整体，或只解除它与某一集的关联。\n\nentire=true 会真正删除资产本体（含全部变体与历史图片），已经绑定该资产的镜头 / 场次会一并解除绑定，请谨慎调用。",
  "tags": [
    "资产"
  ],
  "responses": {
    "200": {
      "description": "删除资产",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "nullable": true
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": null
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "assetId",
      "in": "path",
      "required": true,
      "description": "对外资产号。",
      "schema": {
        "type": "string"
      },
      "example": "as_5Ln9Vt2"
    },
    {
      "name": "entire",
      "in": "query",
      "required": false,
      "description": "true 表示整个资产本体一并删除；false（默认）只解除关联。",
      "schema": {
        "type": "boolean"
      },
      "example": "false"
    },
    {
      "name": "episodeId",
      "in": "query",
      "required": false,
      "description": "仅 entire=false 时生效，圈定解除关联的剧集范围；不传按解除全项目关联处理。",
      "schema": {
        "type": "string"
      }
    }
  ]
}
```

<a id="upload-asset-image"></a>

### POST /assets/{assetId}/images - 上传资产形象图

Operation ID: `upload-asset-image`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=assets-upload-asset-image) | [Saved web text](web-pages/upload-asset-image.txt)

把已上传的图片文件设为该资产的形象图（默认变体展示图）。

fileId 必须是 purpose=IMAGE 上传的文件，否则返回 415 DRAMA_FILE_UNSUPPORTED；用 purpose=SCRIPT 或 AUDIO 的 fileId 会被拒绝。

版式由后端按资产类型自动选择（场景走平面图、角色走三视图），与「资产生图」接口一致，当前不支持客户端指定版式。

Complete operation specification:

```json
{
  "operationId": "upload-asset-image",
  "summary": "上传资产形象图",
  "description": "把已上传的图片文件设为该资产的形象图（默认变体展示图）。\n\nfileId 必须是 purpose=IMAGE 上传的文件，否则返回 415 DRAMA_FILE_UNSUPPORTED；用 purpose=SCRIPT 或 AUDIO 的 fileId 会被拒绝。\n\n版式由后端按资产类型自动选择（场景走平面图、角色走三视图），与「资产生图」接口一致，当前不支持客户端指定版式。",
  "tags": [
    "资产"
  ],
  "responses": {
    "200": {
      "description": "上传资产形象图",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "nullable": true
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": null
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "assetId",
      "in": "path",
      "required": true,
      "description": "对外资产号。",
      "schema": {
        "type": "string"
      },
      "example": "as_5Ln9Vt2"
    }
  ],
  "requestBody": {
    "required": true,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "fileId": {
              "type": "string",
              "description": "图片文件号，来自 POST /files（purpose=IMAGE）。"
            }
          },
          "required": [
            "fileId"
          ]
        },
        "example": {
          "fileId": "up_9Wq2Kd4"
        }
      }
    }
  }
}
```

<a id="list-asset-images"></a>

### GET /assets/{assetId}/images - 资产图片历史

Operation ID: `list-asset-images`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=assets-list-asset-images) | [Saved web text](web-pages/list-asset-images.txt)

查询该资产默认变体的历史候选图（最多 50 条）。

只返回真正生成成功的候选图（不含进行中 / 失败的生成尝试）。

Complete operation specification:

```json
{
  "operationId": "list-asset-images",
  "summary": "资产图片历史",
  "description": "查询该资产默认变体的历史候选图（最多 50 条）。\n\n只返回真正生成成功的候选图（不含进行中 / 失败的生成尝试）。",
  "tags": [
    "资产"
  ],
  "responses": {
    "200": {
      "description": "资产图片历史",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "array",
                "items": {
                  "type": "object",
                  "properties": {
                    "imageId": {
                      "type": "string",
                      "description": "候选图号，im_ 前缀。"
                    },
                    "url": {
                      "type": "string",
                      "description": "图片可访问地址。"
                    },
                    "selected": {
                      "type": "boolean",
                      "description": "是否为当前生效展示图。"
                    },
                    "status": {
                      "type": "string",
                      "description": "图片来源标记（如上传 / AI 生成 / AI 改图），不是生成中 / 失败这类进度状态；具体取值以实际返回为准。"
                    },
                    "createdAt": {
                      "type": "string",
                      "description": "ISO-8601 创建时间。"
                    }
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": [
              {
                "imageId": "im_8Fw1Hy3",
                "url": "https://cos.runninghub.cn/aivideo/asset-variant/xxx.png?sign=...",
                "selected": true,
                "status": "AI_GENERATED",
                "createdAt": "2026-09-16T09:13:00.000+08:00"
              }
            ]
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "assetId",
      "in": "path",
      "required": true,
      "description": "对外资产号。",
      "schema": {
        "type": "string"
      },
      "example": "as_5Ln9Vt2"
    }
  ]
}
```

<a id="edit-asset-image"></a>

### POST /assets/{assetId}/image-edits - AI 改图

Operation ID: `edit-asset-image`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=assets-edit-asset-image) | [Saved web text](web-pages/edit-asset-image.txt)

用 I2I 模型基于当前形象图做局部修改，异步任务。

前置条件：该资产必须已有默认变体且默认变体已有展示图，或本次请求带了 referenceFileIds，否则返回 409 DRAMA_STAGE_PRECONDITION——请先调用 POST /assets/(assetId)/images 或资产生图。

生图费用按 openapi 现有计价结算，不经过 LLM 阶段的账单器，不会出现在 GET /bills 里。

改图任务可通过 POST /tasks/(taskNo)/cancellations 取消；但不支持 POST /tasks/(taskNo)/retries 重试（重试仅限镜头生图 / 镜头生视频 / 资产生图）。

Complete operation specification:

```json
{
  "operationId": "edit-asset-image",
  "summary": "AI 改图",
  "description": "用 I2I 模型基于当前形象图做局部修改，异步任务。\n\n前置条件：该资产必须已有默认变体且默认变体已有展示图，或本次请求带了 referenceFileIds，否则返回 409 DRAMA_STAGE_PRECONDITION——请先调用 POST /assets/(assetId)/images 或资产生图。\n\n生图费用按 openapi 现有计价结算，不经过 LLM 阶段的账单器，不会出现在 GET /bills 里。\n\n改图任务可通过 POST /tasks/(taskNo)/cancellations 取消；但不支持 POST /tasks/(taskNo)/retries 重试（重试仅限镜头生图 / 镜头生视频 / 资产生图）。",
  "tags": [
    "资产"
  ],
  "responses": {
    "200": {
      "description": "AI 改图",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "taskId": {
                    "type": "string",
                    "description": "任务号。"
                  },
                  "type": {
                    "type": "string",
                    "description": "固定为 ASSET_IMAGE_EDIT。"
                  },
                  "status": {
                    "type": "string",
                    "description": "提交时固定为 QUEUED。"
                  },
                  "progress": {
                    "nullable": true
                  },
                  "result": {
                    "nullable": true,
                    "description": "SUCCEEDED 后为新生成图片的可访问地址。"
                  },
                  "error": {
                    "nullable": true
                  },
                  "cost": {
                    "nullable": true
                  },
                  "createdAt": {
                    "type": "string"
                  },
                  "finishedAt": {
                    "nullable": true
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "taskId": "tk_4Ev8Gx1",
              "type": "ASSET_IMAGE_EDIT",
              "status": "QUEUED",
              "progress": null,
              "result": null,
              "error": null,
              "cost": null,
              "createdAt": "2026-09-17T09:20:00.000+08:00",
              "finishedAt": null
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "Idempotency-Key",
      "in": "header",
      "required": false,
      "description": "幂等键。",
      "schema": {
        "type": "string"
      }
    },
    {
      "name": "assetId",
      "in": "path",
      "required": true,
      "description": "对外资产号。",
      "schema": {
        "type": "string"
      },
      "example": "as_5Ln9Vt2"
    }
  ],
  "requestBody": {
    "required": true,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "appCode": {
              "type": "string",
              "description": "生图应用码，取自 GET /catalog/apps（capability=IMAGE），必须是 I2I 模型，否则返回 422 DRAMA_APP_NOT_AVAILABLE。"
            },
            "prompt": {
              "type": "string",
              "description": "修改说明。"
            },
            "referenceFileIds": {
              "type": "array",
              "items": {
                "type": "string"
              },
              "description": "额外参考图文件号列表（POST /files，purpose=IMAGE），追加在当前默认展示图之后一起参与改图；最多 10 项，超出返回 422。"
            }
          },
          "required": [
            "appCode",
            "prompt"
          ]
        },
        "example": {
          "appCode": "NANO_PRO_G2_I2I_OFFICIAL",
          "prompt": "把上衣换成红色风衣"
        }
      }
    }
  }
}
```

<a id="select-asset-image"></a>

### PUT /assets/{assetId}/selected-image - 选中资产图片

Operation ID: `select-asset-image`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=assets-select-asset-image) | [Saved web text](web-pages/select-asset-image.txt)

把历史候选图中的一张设为当前生效展示图。

imageId 不属于路径里的资产时返回 404 DRAMA_NOT_FOUND。

Complete operation specification:

```json
{
  "operationId": "select-asset-image",
  "summary": "选中资产图片",
  "description": "把历史候选图中的一张设为当前生效展示图。\n\nimageId 不属于路径里的资产时返回 404 DRAMA_NOT_FOUND。",
  "tags": [
    "资产"
  ],
  "responses": {
    "200": {
      "description": "选中资产图片",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "nullable": true
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": null
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "assetId",
      "in": "path",
      "required": true,
      "description": "对外资产号。",
      "schema": {
        "type": "string"
      },
      "example": "as_5Ln9Vt2"
    }
  ],
  "requestBody": {
    "required": true,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "imageId": {
              "type": "string",
              "description": "候选图号，取自「资产图片历史」。"
            }
          },
          "required": [
            "imageId"
          ]
        },
        "example": {
          "imageId": "im_8Fw1Hy3"
        }
      }
    }
  }
}
```

<a id="delete-asset-image"></a>

### DELETE /assets/{assetId}/images/{imageId} - 删除资产图片

Operation ID: `delete-asset-image`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=assets-delete-asset-image) | [Saved web text](web-pages/delete-asset-image.txt)

删除一张历史候选图。

删除当前生效展示图后，展示图会回落到该变体下的其它候选图（若还有）；imageId 存在但不属于该资产返回 404 DRAMA_NOT_FOUND。

Complete operation specification:

```json
{
  "operationId": "delete-asset-image",
  "summary": "删除资产图片",
  "description": "删除一张历史候选图。\n\n删除当前生效展示图后，展示图会回落到该变体下的其它候选图（若还有）；imageId 存在但不属于该资产返回 404 DRAMA_NOT_FOUND。",
  "tags": [
    "资产"
  ],
  "responses": {
    "200": {
      "description": "删除资产图片",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "nullable": true
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": null
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "assetId",
      "in": "path",
      "required": true,
      "description": "对外资产号。",
      "schema": {
        "type": "string"
      },
      "example": "as_5Ln9Vt2"
    },
    {
      "name": "imageId",
      "in": "path",
      "required": true,
      "description": "候选图号。",
      "schema": {
        "type": "string"
      },
      "example": "im_8Fw1Hy3"
    }
  ]
}
```

<a id="list-asset-variants"></a>

### GET /assets/{assetId}/variants - 变体列表

Operation ID: `list-asset-variants`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=assets-list-asset-variants) | [Saved web text](web-pages/list-asset-variants.txt)

查询该资产下的全部变体（服饰 / 表情 / 姿势），不分页。

Complete operation specification:

```json
{
  "operationId": "list-asset-variants",
  "summary": "变体列表",
  "description": "查询该资产下的全部变体（服饰 / 表情 / 姿势），不分页。",
  "tags": [
    "资产"
  ],
  "responses": {
    "200": {
      "description": "变体列表",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "array",
                "items": {
                  "type": "object",
                  "properties": {
                    "variantId": {
                      "type": "string",
                      "description": "变体号，vr_ 前缀。"
                    },
                    "kind": {
                      "type": "string",
                      "description": "变体种类。",
                      "enum": [
                        "OUTFIT",
                        "POSE",
                        "LOOK"
                      ]
                    },
                    "name": {
                      "type": "string",
                      "description": "变体名称。"
                    },
                    "description": {
                      "type": "string",
                      "description": "变体描述文案，参与 AI 生图提示词拼装。"
                    },
                    "imageUrl": {
                      "type": "string",
                      "description": "该变体当前展示图地址，未生图为 null。"
                    },
                    "isDefault": {
                      "type": "boolean",
                      "description": "是否为默认变体。"
                    },
                    "sortOrder": {
                      "type": "number",
                      "description": "排序序号。"
                    }
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": [
              {
                "variantId": "vr_7Nq4Su2",
                "kind": "OUTFIT",
                "name": "日常装",
                "description": "白色衬衫，牛仔裤",
                "imageUrl": "https://cos.runninghub.cn/aivideo/asset-variant/xxx.png?sign=...",
                "isDefault": true,
                "sortOrder": 0
              }
            ]
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "assetId",
      "in": "path",
      "required": true,
      "description": "对外资产号。",
      "schema": {
        "type": "string"
      },
      "example": "as_5Ln9Vt2"
    }
  ]
}
```

<a id="create-asset-variant"></a>

### POST /assets/{assetId}/variants - 创建变体

Operation ID: `create-asset-variant`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=assets-create-asset-variant) | [Saved web text](web-pages/create-asset-variant.txt)

为资产新增一个服饰 / 表情 / 姿势变体。

Complete operation specification:

```json
{
  "operationId": "create-asset-variant",
  "summary": "创建变体",
  "description": "为资产新增一个服饰 / 表情 / 姿势变体。",
  "tags": [
    "资产"
  ],
  "responses": {
    "200": {
      "description": "创建变体",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "variantId": {
                    "type": "string",
                    "description": "变体号。"
                  },
                  "kind": {
                    "type": "string",
                    "description": "变体种类。",
                    "enum": [
                      "OUTFIT",
                      "POSE",
                      "LOOK"
                    ]
                  },
                  "name": {
                    "type": "string",
                    "description": "变体名称。"
                  },
                  "description": {
                    "type": "string",
                    "description": "变体描述文案。"
                  },
                  "imageUrl": {
                    "nullable": true,
                    "description": "刚创建时未生图，恒为 null。"
                  },
                  "isDefault": {
                    "type": "boolean",
                    "description": "是否为默认变体，新建变体一般为 false。"
                  },
                  "sortOrder": {
                    "type": "number",
                    "description": "排序序号。"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "variantId": "vr_8Or5Tv3",
              "kind": "OUTFIT",
              "name": "雨夜装",
              "description": "深色雨衣，湿发",
              "imageUrl": null,
              "isDefault": false,
              "sortOrder": 1
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "assetId",
      "in": "path",
      "required": true,
      "description": "对外资产号。",
      "schema": {
        "type": "string"
      },
      "example": "as_5Ln9Vt2"
    }
  ],
  "requestBody": {
    "required": true,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "name": {
              "type": "string",
              "description": "变体名称。"
            },
            "prompt": {
              "type": "string",
              "description": "变体描述文案，可空。"
            },
            "kind": {
              "type": "string",
              "enum": [
                "OUTFIT",
                "POSE",
                "LOOK"
              ],
              "description": "变体种类，不传由后端按资产类型决定；非法值返回 422 DRAMA_VALIDATION_FAILED。"
            }
          },
          "required": [
            "name"
          ]
        },
        "example": {
          "name": "雨夜装",
          "prompt": "深色雨衣，湿发",
          "kind": "OUTFIT"
        }
      }
    }
  }
}
```

<a id="update-asset-variant"></a>

### PATCH /assets/{assetId}/variants/{variantId} - 更新变体

Operation ID: `update-asset-variant`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=assets-update-asset-variant) | [Saved web text](web-pages/update-asset-variant.txt)

修改变体名称 / 描述文案，字段为空不修改。

Complete operation specification:

```json
{
  "operationId": "update-asset-variant",
  "summary": "更新变体",
  "description": "修改变体名称 / 描述文案，字段为空不修改。",
  "tags": [
    "资产"
  ],
  "responses": {
    "200": {
      "description": "更新变体",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "variantId": {
                    "type": "string",
                    "description": "变体号。"
                  },
                  "kind": {
                    "type": "string",
                    "description": "变体种类。",
                    "enum": [
                      "OUTFIT",
                      "POSE",
                      "LOOK"
                    ]
                  },
                  "name": {
                    "type": "string",
                    "description": "变体名称。"
                  },
                  "description": {
                    "type": "string",
                    "description": "变体描述文案。"
                  },
                  "imageUrl": {
                    "type": "string",
                    "description": "当前展示图地址。"
                  },
                  "isDefault": {
                    "type": "boolean",
                    "description": "是否为默认变体。"
                  },
                  "sortOrder": {
                    "type": "number",
                    "description": "排序序号。"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "variantId": "vr_7Nq4Su2",
              "kind": "OUTFIT",
              "name": "日常装",
              "description": "深色雨衣，湿发，手持雨伞",
              "imageUrl": "https://cos.runninghub.cn/aivideo/asset-variant/xxx.png?sign=...",
              "isDefault": true,
              "sortOrder": 0
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "assetId",
      "in": "path",
      "required": true,
      "description": "对外资产号。",
      "schema": {
        "type": "string"
      },
      "example": "as_5Ln9Vt2"
    },
    {
      "name": "variantId",
      "in": "path",
      "required": true,
      "description": "变体号。",
      "schema": {
        "type": "string"
      },
      "example": "vr_7Nq4Su2"
    }
  ],
  "requestBody": {
    "required": false,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "name": {
              "type": "string",
              "description": "新名称，不传则不改。"
            },
            "prompt": {
              "type": "string",
              "description": "新描述文案，不传则不改。"
            }
          }
        },
        "example": {
          "prompt": "深色雨衣，湿发，手持雨伞"
        }
      }
    }
  }
}
```

<a id="delete-asset-variant"></a>

### DELETE /assets/{assetId}/variants/{variantId} - 删除变体

Operation ID: `delete-asset-variant`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=assets-delete-asset-variant) | [Saved web text](web-pages/delete-asset-variant.txt)

删除一个变体及其历史图片。

删除默认变体的具体后果（是否自动指定新默认变体）取决于内部服务实现，调用前建议先确认该变体不是默认变体。

Complete operation specification:

```json
{
  "operationId": "delete-asset-variant",
  "summary": "删除变体",
  "description": "删除一个变体及其历史图片。\n\n删除默认变体的具体后果（是否自动指定新默认变体）取决于内部服务实现，调用前建议先确认该变体不是默认变体。",
  "tags": [
    "资产"
  ],
  "responses": {
    "200": {
      "description": "删除变体",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "nullable": true
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": null
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "assetId",
      "in": "path",
      "required": true,
      "description": "对外资产号。",
      "schema": {
        "type": "string"
      },
      "example": "as_5Ln9Vt2"
    },
    {
      "name": "variantId",
      "in": "path",
      "required": true,
      "description": "变体号。",
      "schema": {
        "type": "string"
      },
      "example": "vr_8Or5Tv3"
    }
  ]
}
```

<a id="update-asset-style"></a>

### PUT /assets/{assetId}/style - 绑定资产画风

Operation ID: `update-asset-style`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=assets-update-asset-style) | [Saved web text](web-pages/update-asset-style.txt)

为单个资产单独指定自定义画风，覆盖项目全局画风。

重要：这里的 stylePresetId 必须是「自定义画风」分组下 st_ 前缀的用户画风号，不是 GET /catalog/styles 返回的内置画风数字 id——传内置画风的数字字符串会因为前缀不匹配返回 404 DRAMA_NOT_FOUND。

Complete operation specification:

```json
{
  "operationId": "update-asset-style",
  "summary": "绑定资产画风",
  "description": "为单个资产单独指定自定义画风，覆盖项目全局画风。\n\n重要：这里的 stylePresetId 必须是「自定义画风」分组下 st_ 前缀的用户画风号，不是 GET /catalog/styles 返回的内置画风数字 id——传内置画风的数字字符串会因为前缀不匹配返回 404 DRAMA_NOT_FOUND。",
  "tags": [
    "资产"
  ],
  "responses": {
    "200": {
      "description": "绑定资产画风",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "nullable": true
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": null
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "assetId",
      "in": "path",
      "required": true,
      "description": "对外资产号。",
      "schema": {
        "type": "string"
      },
      "example": "as_5Ln9Vt2"
    }
  ],
  "requestBody": {
    "required": false,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "stylePresetId": {
              "type": "string",
              "description": "自定义画风号（POST /styles/custom 返回的 styleId，st_ 前缀），传 null 或不传表示清除单独设置、回落项目全局画风。"
            }
          }
        },
        "example": {
          "stylePresetId": "st_2Kd7Nx9"
        }
      }
    }
  }
}
```

<a id="update-asset-scenes"></a>

### PUT /assets/{assetId}/scenes - 设置资产出场场次

Operation ID: `update-asset-scenes`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=assets-update-asset-scenes) | [Saved web text](web-pages/update-asset-scenes.txt)

整表替换该资产（场景 / 道具）的出场场次。

只对 SCENE / PROP 类型资产有效；CHARACTER 资产的出场场次挂在变体绑定上，调用本接口对角色资产无意义。

Complete operation specification:

```json
{
  "operationId": "update-asset-scenes",
  "summary": "设置资产出场场次",
  "description": "整表替换该资产（场景 / 道具）的出场场次。\n\n只对 SCENE / PROP 类型资产有效；CHARACTER 资产的出场场次挂在变体绑定上，调用本接口对角色资产无意义。",
  "tags": [
    "资产"
  ],
  "responses": {
    "200": {
      "description": "设置资产出场场次",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "nullable": true
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": null
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "assetId",
      "in": "path",
      "required": true,
      "description": "对外资产号。",
      "schema": {
        "type": "string"
      },
      "example": "as_5Ln9Vt2"
    }
  ],
  "requestBody": {
    "required": true,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "sceneIds": {
              "type": "array",
              "items": {
                "type": "string"
              },
              "description": "出场场次号列表，整表替换（不在列表里的旧关联会被移除）；最多 200 项，超出返回 422。"
            }
          },
          "required": [
            "sceneIds"
          ]
        },
        "example": {
          "sceneIds": [
            "sc_6Ym2Wq9"
          ]
        }
      }
    }
  }
}
```

<a id="update-shot-assets"></a>

### PUT /shots/{shotId}/assets - 设置镜头绑定资产

Operation ID: `update-shot-assets`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=assets-update-shot-assets) | [Saved web text](web-pages/update-shot-assets.txt)

整表替换该镜头绑定的资产（角色 / 场景 / 道具）。

资产的变体不会被本接口覆盖，走各自的继承链（默认变体 / 场景当前展示图）。

Complete operation specification:

```json
{
  "operationId": "update-shot-assets",
  "summary": "设置镜头绑定资产",
  "description": "整表替换该镜头绑定的资产（角色 / 场景 / 道具）。\n\n资产的变体不会被本接口覆盖，走各自的继承链（默认变体 / 场景当前展示图）。",
  "tags": [
    "资产"
  ],
  "responses": {
    "200": {
      "description": "设置镜头绑定资产",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "nullable": true
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": null
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "shotId",
      "in": "path",
      "required": true,
      "description": "对外镜头号。",
      "schema": {
        "type": "string"
      },
      "example": "sh_7Qz3Rk9"
    }
  ],
  "requestBody": {
    "required": true,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "assetIds": {
              "type": "array",
              "items": {
                "type": "string"
              },
              "description": "资产号列表，整表替换（不在列表里的旧绑定会被解除，新出现的会补绑）；最多 200 项，超出返回 422。"
            }
          },
          "required": [
            "assetIds"
          ]
        },
        "example": {
          "assetIds": [
            "as_5Ln9Vt2",
            "as_6Mp3Rs1"
          ]
        }
      }
    }
  }
}
```


<a id="group-09"></a>

## 分场与分镜

<a id="list-scenes"></a>

### GET /episodes/{episodeId}/scenes - 场次列表

Operation ID: `list-scenes`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=storyboard-list-scenes) | [Saved web text](web-pages/list-scenes.txt)

查询该集全部场次（不分页）。

Complete operation specification:

```json
{
  "operationId": "list-scenes",
  "summary": "场次列表",
  "description": "查询该集全部场次（不分页）。",
  "tags": [
    "分场与分镜"
  ],
  "responses": {
    "200": {
      "description": "场次列表",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "array",
                "items": {
                  "type": "object",
                  "properties": {
                    "sceneId": {
                      "type": "string",
                      "description": "对外场次号，sc_ 前缀。"
                    },
                    "sceneIndex": {
                      "type": "number",
                      "description": "场次序号，从 1 开始。"
                    },
                    "title": {
                      "type": "string",
                      "description": "场次标题。"
                    },
                    "summary": {
                      "type": "string",
                      "description": "场次摘要。"
                    },
                    "status": {
                      "type": "string",
                      "description": "本场的分镜生成状态（不是场次综合状态），用于判断能否发起 shot-rebuilds：IDLE 未生成、GENERATING 生成中、DONE 已完成、FAILED 上次生成失败。",
                      "enum": [
                        "IDLE",
                        "GENERATING",
                        "DONE",
                        "FAILED"
                      ]
                    }
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": [
              {
                "sceneId": "sc_6Ym2Wq9",
                "sceneIndex": 1,
                "title": "雨夜街头",
                "summary": "林夏在雨中奔跑，遇见神秘人。",
                "status": "DONE"
              }
            ]
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "episodeId",
      "in": "path",
      "required": true,
      "description": "对外剧集号。",
      "schema": {
        "type": "string"
      },
      "example": "ep_4Rt7QxNp1"
    }
  ]
}
```

<a id="create-scene"></a>

### POST /episodes/{episodeId}/scenes - 创建场次

Operation ID: `create-scene`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=storyboard-create-scene) | [Saved web text](web-pages/create-scene.txt)

在指定剧集下手动插入一个场次。

afterSceneId 不属于该集时返回 404 DRAMA_NOT_FOUND。

不支持 Idempotency-Key，重复提交会创建多个场次。

Complete operation specification:

```json
{
  "operationId": "create-scene",
  "summary": "创建场次",
  "description": "在指定剧集下手动插入一个场次。\n\nafterSceneId 不属于该集时返回 404 DRAMA_NOT_FOUND。\n\n不支持 Idempotency-Key，重复提交会创建多个场次。",
  "tags": [
    "分场与分镜"
  ],
  "responses": {
    "200": {
      "description": "创建场次",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "sceneId": {
                    "type": "string",
                    "description": "对外场次号。"
                  },
                  "sceneIndex": {
                    "type": "number",
                    "description": "场次序号。"
                  },
                  "title": {
                    "type": "string",
                    "description": "场次标题。"
                  },
                  "summary": {
                    "nullable": true,
                    "description": "场次摘要，手动创建时为 null。"
                  },
                  "status": {
                    "type": "string",
                    "description": "分镜生成状态，新建时为 IDLE。",
                    "enum": [
                      "IDLE",
                      "GENERATING",
                      "DONE",
                      "FAILED"
                    ]
                  },
                  "content": {
                    "type": "string",
                    "description": "场次正文。"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "sceneId": "sc_8Pr4Ty6",
              "sceneIndex": 2,
              "title": "场景二：便利店",
              "summary": null,
              "status": "IDLE",
              "content": "林夏走进便利店，货架上只剩最后一盏应急灯……"
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "episodeId",
      "in": "path",
      "required": true,
      "description": "对外剧集号。",
      "schema": {
        "type": "string"
      },
      "example": "ep_4Rt7QxNp1"
    }
  ],
  "requestBody": {
    "required": true,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "title": {
              "type": "string",
              "description": "场次标题。"
            },
            "content": {
              "type": "string",
              "description": "场次正文。"
            },
            "afterSceneId": {
              "type": "string",
              "description": "插入锚点：新场次紧跟该场次之后；不传则追加到剧集末尾。"
            }
          },
          "required": [
            "title",
            "content"
          ]
        },
        "example": {
          "title": "场景二：便利店",
          "content": "林夏走进便利店，货架上只剩最后一盏应急灯……"
        }
      }
    }
  }
}
```

<a id="get-scene-detail"></a>

### GET /scenes/{sceneId} - 查询场次详情

Operation ID: `get-scene-detail`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=storyboard-get-scene-detail) | [Saved web text](web-pages/get-scene-detail.txt)

按场次号查询详情，含正文。

不属于当前企业 Key 或 id 不合法都返回 404 DRAMA_NOT_FOUND。

Complete operation specification:

```json
{
  "operationId": "get-scene-detail",
  "summary": "查询场次详情",
  "description": "按场次号查询详情，含正文。\n\n不属于当前企业 Key 或 id 不合法都返回 404 DRAMA_NOT_FOUND。",
  "tags": [
    "分场与分镜"
  ],
  "responses": {
    "200": {
      "description": "查询场次详情",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "sceneId": {
                    "type": "string",
                    "description": "对外场次号。"
                  },
                  "sceneIndex": {
                    "type": "number",
                    "description": "场次序号，从 1 开始。"
                  },
                  "title": {
                    "type": "string",
                    "description": "场次标题。"
                  },
                  "summary": {
                    "type": "string",
                    "description": "场次摘要。"
                  },
                  "status": {
                    "type": "string",
                    "description": "本场的分镜生成状态，同「场次列表」的 status。",
                    "enum": [
                      "IDLE",
                      "GENERATING",
                      "DONE",
                      "FAILED"
                    ]
                  },
                  "content": {
                    "type": "string",
                    "description": "场次正文。"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "sceneId": "sc_6Ym2Wq9",
              "sceneIndex": 1,
              "title": "雨夜街头",
              "summary": "林夏在雨中奔跑，遇见神秘人。",
              "status": "DONE",
              "content": "雨夜，林夏疾步奔跑在空无一人的街道上……"
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "sceneId",
      "in": "path",
      "required": true,
      "description": "对外场次号。",
      "schema": {
        "type": "string"
      },
      "example": "sc_6Ym2Wq9"
    }
  ]
}
```

<a id="update-scene"></a>

### PATCH /scenes/{sceneId} - 更新场次

Operation ID: `update-scene`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=storyboard-update-scene) | [Saved web text](web-pages/update-scene.txt)

修改场次标题 / 正文，字段为空不修改。

改动正文不会自动重建下游镜头，已有分镜仍保留原样；需要刷新请另外调用 POST /scenes/(sceneId)/shot-rebuilds。

Complete operation specification:

```json
{
  "operationId": "update-scene",
  "summary": "更新场次",
  "description": "修改场次标题 / 正文，字段为空不修改。\n\n改动正文不会自动重建下游镜头，已有分镜仍保留原样；需要刷新请另外调用 POST /scenes/(sceneId)/shot-rebuilds。",
  "tags": [
    "分场与分镜"
  ],
  "responses": {
    "200": {
      "description": "更新场次",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "sceneId": {
                    "type": "string",
                    "description": "对外场次号。"
                  },
                  "sceneIndex": {
                    "type": "number",
                    "description": "场次序号。"
                  },
                  "title": {
                    "type": "string",
                    "description": "场次标题。"
                  },
                  "summary": {
                    "type": "string",
                    "description": "场次摘要。"
                  },
                  "status": {
                    "type": "string",
                    "description": "分镜生成状态。",
                    "enum": [
                      "IDLE",
                      "GENERATING",
                      "DONE",
                      "FAILED"
                    ]
                  },
                  "content": {
                    "type": "string",
                    "description": "场次正文。"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "sceneId": "sc_6Ym2Wq9",
              "sceneIndex": 1,
              "title": "雨夜街头",
              "summary": "林夏在雨中奔跑，遇见神秘人。",
              "status": "DONE",
              "content": "雨夜，林夏疾步奔跑在空无一人的街道上……（改写版）"
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "sceneId",
      "in": "path",
      "required": true,
      "description": "对外场次号。",
      "schema": {
        "type": "string"
      },
      "example": "sc_6Ym2Wq9"
    }
  ],
  "requestBody": {
    "required": false,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "title": {
              "type": "string",
              "description": "新标题，不传则不改。"
            },
            "content": {
              "type": "string",
              "description": "新正文，不传则不改。"
            }
          }
        },
        "example": {
          "content": "雨夜，林夏疾步奔跑在空无一人的街道上……（改写版）"
        }
      }
    }
  }
}
```

<a id="delete-scene"></a>

### DELETE /scenes/{sceneId} - 删除场次

Operation ID: `delete-scene`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=storyboard-delete-scene) | [Saved web text](web-pages/delete-scene.txt)

软删除一个场次，级联软删其下全部镜头及镜头视频。

级联删除范围包括该场次下所有镜头及其镜头视频，删除后无法恢复，请谨慎调用。

Complete operation specification:

```json
{
  "operationId": "delete-scene",
  "summary": "删除场次",
  "description": "软删除一个场次，级联软删其下全部镜头及镜头视频。\n\n级联删除范围包括该场次下所有镜头及其镜头视频，删除后无法恢复，请谨慎调用。",
  "tags": [
    "分场与分镜"
  ],
  "responses": {
    "200": {
      "description": "删除场次",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "nullable": true
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": null
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "sceneId",
      "in": "path",
      "required": true,
      "description": "对外场次号。",
      "schema": {
        "type": "string"
      },
      "example": "sc_6Ym2Wq9"
    }
  ]
}
```

<a id="reorder-scenes"></a>

### PUT /episodes/{episodeId}/scene-order - 场次重新排序

Operation ID: `reorder-scenes`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=storyboard-reorder-scenes) | [Saved web text](web-pages/reorder-scenes.txt)

按给定顺序重排该集的场次。

sceneIds 中任意一个不属于路径里的 episodeId 都会返回 404 DRAMA_NOT_FOUND，整批不生效。

Complete operation specification:

```json
{
  "operationId": "reorder-scenes",
  "summary": "场次重新排序",
  "description": "按给定顺序重排该集的场次。\n\nsceneIds 中任意一个不属于路径里的 episodeId 都会返回 404 DRAMA_NOT_FOUND，整批不生效。",
  "tags": [
    "分场与分镜"
  ],
  "responses": {
    "200": {
      "description": "场次重新排序",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "nullable": true
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": null
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "episodeId",
      "in": "path",
      "required": true,
      "description": "对外剧集号。",
      "schema": {
        "type": "string"
      },
      "example": "ep_4Rt7QxNp1"
    }
  ],
  "requestBody": {
    "required": true,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "sceneIds": {
              "type": "array",
              "items": {
                "type": "string"
              },
              "description": "按目标顺序排列的场次号列表，最多 200 项（超出返回 422）；建议一次性传入该集全部未删场次的 id，未包含在列表里的场次相对顺序由内部实现决定，不保证符合预期。"
            }
          },
          "required": [
            "sceneIds"
          ]
        },
        "example": {
          "sceneIds": [
            "sc_8Pr4Ty6",
            "sc_6Ym2Wq9"
          ]
        }
      }
    }
  }
}
```

<a id="merge-scenes"></a>

### POST /scene-merges - 合并场次

Operation ID: `merge-scenes`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=storyboard-merge-scenes) | [Saved web text](web-pages/merge-scenes.txt)

把两个场次合并为一个（第二个合入第一个）。

sceneIds 数量不为 2，或任一 id 不合法 / 不属于当前 Key，分别返回 422 DRAMA_VALIDATION_FAILED / 404 DRAMA_NOT_FOUND。

Complete operation specification:

```json
{
  "operationId": "merge-scenes",
  "summary": "合并场次",
  "description": "把两个场次合并为一个（第二个合入第一个）。\n\nsceneIds 数量不为 2，或任一 id 不合法 / 不属于当前 Key，分别返回 422 DRAMA_VALIDATION_FAILED / 404 DRAMA_NOT_FOUND。",
  "tags": [
    "分场与分镜"
  ],
  "responses": {
    "200": {
      "description": "合并场次",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "sceneId": {
                    "type": "string",
                    "description": "合并后仍存在的场次号（即传入的第 1 个）。"
                  },
                  "sceneIndex": {
                    "type": "number",
                    "description": "场次序号。"
                  },
                  "title": {
                    "type": "string",
                    "description": "场次标题。"
                  },
                  "summary": {
                    "type": "string",
                    "description": "场次摘要。"
                  },
                  "status": {
                    "type": "string",
                    "description": "分镜生成状态。",
                    "enum": [
                      "IDLE",
                      "GENERATING",
                      "DONE",
                      "FAILED"
                    ]
                  },
                  "content": {
                    "type": "string",
                    "description": "合并后的正文。"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "sceneId": "sc_6Ym2Wq9",
              "sceneIndex": 1,
              "title": "雨夜街头",
              "summary": "林夏在雨中奔跑，遇见神秘人。",
              "status": "DONE",
              "content": "雨夜，林夏疾步奔跑在空无一人的街道上……\n林夏走进便利店，货架上只剩最后一盏应急灯……"
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "requestBody": {
    "required": true,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "sceneIds": {
              "type": "array",
              "items": {
                "type": "string"
              },
              "description": "必须正好传 2 个场次号（数量不为 2 返回 422 DRAMA_VALIDATION_FAILED），第 2 个合入第 1 个；第 2 个场次会被软删。"
            }
          },
          "required": [
            "sceneIds"
          ]
        },
        "example": {
          "sceneIds": [
            "sc_6Ym2Wq9",
            "sc_8Pr4Ty6"
          ]
        }
      }
    }
  }
}
```

<a id="refine-scene"></a>

### POST /scenes/{sceneId}/refinements - AI 改写场次

Operation ID: `refine-scene`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=storyboard-refine-scene) | [Saved web text](web-pages/refine-scene.txt)

按指令用 AI 改写场次正文，异步任务；不传指令时使用默认通用润色指令。

同一集同一时间只能有一个场次在 AI 改写：其他场次的改写进行中时返回 409 DRAMA_OPERATION_NOT_ALLOWED，等其完成后再提交；同一场重复提交返回进行中的那个任务。

计费：按任务内模型调用的实际费用（网关标价，不加价）在任务终态一次性结算——成功扣款，失败不扣，取消按已消耗量扣（含取消时仍在进行的调用，账单在任务实际停止后结算）；金额按分四舍五入；模型由平台统一配置，不可指定。提交时余额需大于 0（团队 Key 看团队钱包，非团队 Key 看企业账户余额），否则返回 402 DRAMA_BALANCE_INSUFFICIENT；结算可能把余额扣成负数，之后的计费任务会被拦截直到充值。结算时若因系统原因扣款失败，账单记为欠费（ARREARS / ARREARS_PARTIAL_CANCELED），由平台自动补扣，不影响继续提交。任务从提交到终态占用一个企业 Key 并发名额（GET /quota 的 concurrentLimit），已满返回 429 DRAMA_CONCURRENCY_LIMIT，稍后重试。可用 GET /bills 查账单。

Complete operation specification:

```json
{
  "operationId": "refine-scene",
  "summary": "AI 改写场次",
  "description": "按指令用 AI 改写场次正文，异步任务；不传指令时使用默认通用润色指令。\n\n同一集同一时间只能有一个场次在 AI 改写：其他场次的改写进行中时返回 409 DRAMA_OPERATION_NOT_ALLOWED，等其完成后再提交；同一场重复提交返回进行中的那个任务。\n\n计费：按任务内模型调用的实际费用（网关标价，不加价）在任务终态一次性结算——成功扣款，失败不扣，取消按已消耗量扣（含取消时仍在进行的调用，账单在任务实际停止后结算）；金额按分四舍五入；模型由平台统一配置，不可指定。提交时余额需大于 0（团队 Key 看团队钱包，非团队 Key 看企业账户余额），否则返回 402 DRAMA_BALANCE_INSUFFICIENT；结算可能把余额扣成负数，之后的计费任务会被拦截直到充值。结算时若因系统原因扣款失败，账单记为欠费（ARREARS / ARREARS_PARTIAL_CANCELED），由平台自动补扣，不影响继续提交。任务从提交到终态占用一个企业 Key 并发名额（GET /quota 的 concurrentLimit），已满返回 429 DRAMA_CONCURRENCY_LIMIT，稍后重试。可用 GET /bills 查账单。",
  "tags": [
    "分场与分镜"
  ],
  "responses": {
    "200": {
      "description": "AI 改写场次",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "taskId": {
                    "type": "string",
                    "description": "任务号。"
                  },
                  "type": {
                    "type": "string",
                    "description": "固定为 SCENE_REFINE。"
                  },
                  "status": {
                    "type": "string"
                  },
                  "progress": {
                    "nullable": true
                  },
                  "result": {
                    "nullable": true,
                    "description": "SUCCEEDED 后内容以内部改写服务的实际返回为准，未强类型约定；建议成功后另外调用 GET /scenes/(sceneId) 确认最新正文。"
                  },
                  "error": {
                    "nullable": true
                  },
                  "cost": {
                    "nullable": true
                  },
                  "createdAt": {
                    "type": "string"
                  },
                  "finishedAt": {
                    "nullable": true
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "taskId": "tk_6Gz9Ib3",
              "type": "SCENE_REFINE",
              "status": "QUEUED",
              "progress": null,
              "result": null,
              "error": null,
              "cost": null,
              "createdAt": "2026-09-17T09:25:00.000+08:00",
              "finishedAt": null
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "Idempotency-Key",
      "in": "header",
      "required": false,
      "description": "幂等键。",
      "schema": {
        "type": "string"
      }
    },
    {
      "name": "sceneId",
      "in": "path",
      "required": true,
      "description": "对外场次号。",
      "schema": {
        "type": "string"
      },
      "example": "sc_6Ym2Wq9"
    }
  ],
  "requestBody": {
    "required": false,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "instruction": {
              "type": "string",
              "description": "改写指令；不传则使用后端默认的通用润色指令（保持剧情与关键信息不变、使正文更流畅自然）。"
            }
          }
        },
        "example": {
          "instruction": "把这场的悬疑感加强一些"
        }
      }
    }
  }
}
```

<a id="generate-storyboard"></a>

### POST /episodes/{episodeId}/storyboards - 整集生成分镜

Operation ID: `generate-storyboard`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=storyboard-generate-storyboard) | [Saved web text](web-pages/generate-storyboard.txt)

用 LLM 为该集所有场次批量生成镜头分镜，异步任务。

前置条件：该集必须已有场次（默认由 asset-extractions 一并产出），否则 409 DRAMA_STAGE_PRECONDITION。

整集分镜会对所有场次重新生成，旧分镜与已生成的镜头视频会被归档覆盖。部分场次失败时任务 FAILED，已成功场次的新分镜保留、不扣费；重试会全量重跑。

剧本已修改但尚未重新确认场次时，提交即同步返回 409 DRAMA_STAGE_PRECONDITION，不会创建任务。更新剧本（PUT /episodes/{episodeId}/script）、AI 润色剧本、手动新建场次、编辑场次正文、合并场次、AI 改写场次都会让场次与剧本失去对齐，需先调用 POST /episodes/{episodeId}/asset-extractions 按最新剧本重新确认场次。注意：重新确认会按最新剧本重新拆分该集场次并归档旧场次 / 分镜 / 视频，手动做的场次编辑会被覆盖；如需改内容，建议改剧本后重新确认，而不是直接改场次（与网页端行为一致）。

storyboards / shot-rebuilds 等阶段接口不接收请求体；asset-extractions 可选传 stylePresetId。使用的模型由平台按阶段统一配置，与网页端效果一致。

计费：按任务内模型调用的实际费用（网关标价，不加价）在任务终态一次性结算——成功扣款，失败不扣，取消按已消耗量扣（含取消时仍在进行的调用，账单在任务实际停止后结算）；金额按分四舍五入；模型由平台统一配置，不可指定。提交时余额需大于 0（团队 Key 看团队钱包，非团队 Key 看企业账户余额），否则返回 402 DRAMA_BALANCE_INSUFFICIENT；结算可能把余额扣成负数，之后的计费任务会被拦截直到充值。结算时若因系统原因扣款失败，账单记为欠费（ARREARS / ARREARS_PARTIAL_CANCELED），由平台自动补扣，不影响继续提交。任务从提交到终态占用一个企业 Key 并发名额（GET /quota 的 concurrentLimit），已满返回 429 DRAMA_CONCURRENCY_LIMIT，稍后重试。可用 GET /bills 查账单。

Complete operation specification:

```json
{
  "operationId": "generate-storyboard",
  "summary": "整集生成分镜",
  "description": "用 LLM 为该集所有场次批量生成镜头分镜，异步任务。\n\n前置条件：该集必须已有场次（默认由 asset-extractions 一并产出），否则 409 DRAMA_STAGE_PRECONDITION。\n\n整集分镜会对所有场次重新生成，旧分镜与已生成的镜头视频会被归档覆盖。部分场次失败时任务 FAILED，已成功场次的新分镜保留、不扣费；重试会全量重跑。\n\n剧本已修改但尚未重新确认场次时，提交即同步返回 409 DRAMA_STAGE_PRECONDITION，不会创建任务。更新剧本（PUT /episodes/{episodeId}/script）、AI 润色剧本、手动新建场次、编辑场次正文、合并场次、AI 改写场次都会让场次与剧本失去对齐，需先调用 POST /episodes/{episodeId}/asset-extractions 按最新剧本重新确认场次。注意：重新确认会按最新剧本重新拆分该集场次并归档旧场次 / 分镜 / 视频，手动做的场次编辑会被覆盖；如需改内容，建议改剧本后重新确认，而不是直接改场次（与网页端行为一致）。\n\nstoryboards / shot-rebuilds 等阶段接口不接收请求体；asset-extractions 可选传 stylePresetId。使用的模型由平台按阶段统一配置，与网页端效果一致。\n\n计费：按任务内模型调用的实际费用（网关标价，不加价）在任务终态一次性结算——成功扣款，失败不扣，取消按已消耗量扣（含取消时仍在进行的调用，账单在任务实际停止后结算）；金额按分四舍五入；模型由平台统一配置，不可指定。提交时余额需大于 0（团队 Key 看团队钱包，非团队 Key 看企业账户余额），否则返回 402 DRAMA_BALANCE_INSUFFICIENT；结算可能把余额扣成负数，之后的计费任务会被拦截直到充值。结算时若因系统原因扣款失败，账单记为欠费（ARREARS / ARREARS_PARTIAL_CANCELED），由平台自动补扣，不影响继续提交。任务从提交到终态占用一个企业 Key 并发名额（GET /quota 的 concurrentLimit），已满返回 429 DRAMA_CONCURRENCY_LIMIT，稍后重试。可用 GET /bills 查账单。",
  "tags": [
    "分场与分镜"
  ],
  "responses": {
    "200": {
      "description": "整集生成分镜",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "taskId": {
                    "type": "string",
                    "description": "任务号。"
                  },
                  "type": {
                    "type": "string",
                    "description": "固定为 STORYBOARD_GENERATE。"
                  },
                  "status": {
                    "type": "string",
                    "description": "提交时固定为 QUEUED。"
                  },
                  "progress": {
                    "nullable": true
                  },
                  "result": {
                    "nullable": true,
                    "description": "SUCCEEDED 后为本次生成的镜头统计信息，如 shotsCount。"
                  },
                  "error": {
                    "nullable": true
                  },
                  "cost": {
                    "nullable": true
                  },
                  "createdAt": {
                    "type": "string"
                  },
                  "finishedAt": {
                    "nullable": true
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "taskId": "tk_6Xo4Nq1",
              "type": "STORYBOARD_GENERATE",
              "status": "QUEUED",
              "progress": null,
              "result": null,
              "error": null,
              "cost": null,
              "createdAt": "2026-09-16T09:25:00.000+08:00",
              "finishedAt": null
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "Idempotency-Key",
      "in": "header",
      "required": false,
      "description": "幂等键。",
      "schema": {
        "type": "string"
      }
    },
    {
      "name": "episodeId",
      "in": "path",
      "required": true,
      "description": "对外剧集号。",
      "schema": {
        "type": "string"
      },
      "example": "ep_4Rt7QxNp1"
    }
  ],
  "requestBody": {
    "required": false,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {}
        },
        "example": {}
      }
    }
  }
}
```

<a id="rebuild-shots"></a>

### POST /scenes/{sceneId}/shot-rebuilds - 单场重建分镜

Operation ID: `rebuild-shots`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=storyboard-rebuild-shots) | [Saved web text](web-pages/rebuild-shots.txt)

用 LLM 只重新生成指定场次的镜头分镜，异步任务。

只影响这一场，其余场次镜头不受影响；该场旧分镜与已生成的镜头视频会被归档覆盖，失败不扣费。

同一集同一时间只能有一个场次在重建分镜：其他场次进行中时返回 409 DRAMA_OPERATION_NOT_ALLOWED，等其完成后再提交；同一场重复提交返回进行中的那个任务。

剧本已修改但尚未重新确认场次时，提交即同步返回 409 DRAMA_STAGE_PRECONDITION，不会创建任务。更新剧本（PUT /episodes/{episodeId}/script）、AI 润色剧本、手动新建场次、编辑场次正文、合并场次、AI 改写场次都会让场次与剧本失去对齐，需先调用 POST /episodes/{episodeId}/asset-extractions 按最新剧本重新确认场次。注意：重新确认会按最新剧本重新拆分该集场次并归档旧场次 / 分镜 / 视频，手动做的场次编辑会被覆盖；如需改内容，建议改剧本后重新确认，而不是直接改场次（与网页端行为一致）。

storyboards / shot-rebuilds 等阶段接口不接收请求体；asset-extractions 可选传 stylePresetId。使用的模型由平台按阶段统一配置，与网页端效果一致。

计费：按任务内模型调用的实际费用（网关标价，不加价）在任务终态一次性结算——成功扣款，失败不扣，取消按已消耗量扣（含取消时仍在进行的调用，账单在任务实际停止后结算）；金额按分四舍五入；模型由平台统一配置，不可指定。提交时余额需大于 0（团队 Key 看团队钱包，非团队 Key 看企业账户余额），否则返回 402 DRAMA_BALANCE_INSUFFICIENT；结算可能把余额扣成负数，之后的计费任务会被拦截直到充值。结算时若因系统原因扣款失败，账单记为欠费（ARREARS / ARREARS_PARTIAL_CANCELED），由平台自动补扣，不影响继续提交。任务从提交到终态占用一个企业 Key 并发名额（GET /quota 的 concurrentLimit），已满返回 429 DRAMA_CONCURRENCY_LIMIT，稍后重试。可用 GET /bills 查账单。

Complete operation specification:

```json
{
  "operationId": "rebuild-shots",
  "summary": "单场重建分镜",
  "description": "用 LLM 只重新生成指定场次的镜头分镜，异步任务。\n\n只影响这一场，其余场次镜头不受影响；该场旧分镜与已生成的镜头视频会被归档覆盖，失败不扣费。\n\n同一集同一时间只能有一个场次在重建分镜：其他场次进行中时返回 409 DRAMA_OPERATION_NOT_ALLOWED，等其完成后再提交；同一场重复提交返回进行中的那个任务。\n\n剧本已修改但尚未重新确认场次时，提交即同步返回 409 DRAMA_STAGE_PRECONDITION，不会创建任务。更新剧本（PUT /episodes/{episodeId}/script）、AI 润色剧本、手动新建场次、编辑场次正文、合并场次、AI 改写场次都会让场次与剧本失去对齐，需先调用 POST /episodes/{episodeId}/asset-extractions 按最新剧本重新确认场次。注意：重新确认会按最新剧本重新拆分该集场次并归档旧场次 / 分镜 / 视频，手动做的场次编辑会被覆盖；如需改内容，建议改剧本后重新确认，而不是直接改场次（与网页端行为一致）。\n\nstoryboards / shot-rebuilds 等阶段接口不接收请求体；asset-extractions 可选传 stylePresetId。使用的模型由平台按阶段统一配置，与网页端效果一致。\n\n计费：按任务内模型调用的实际费用（网关标价，不加价）在任务终态一次性结算——成功扣款，失败不扣，取消按已消耗量扣（含取消时仍在进行的调用，账单在任务实际停止后结算）；金额按分四舍五入；模型由平台统一配置，不可指定。提交时余额需大于 0（团队 Key 看团队钱包，非团队 Key 看企业账户余额），否则返回 402 DRAMA_BALANCE_INSUFFICIENT；结算可能把余额扣成负数，之后的计费任务会被拦截直到充值。结算时若因系统原因扣款失败，账单记为欠费（ARREARS / ARREARS_PARTIAL_CANCELED），由平台自动补扣，不影响继续提交。任务从提交到终态占用一个企业 Key 并发名额（GET /quota 的 concurrentLimit），已满返回 429 DRAMA_CONCURRENCY_LIMIT，稍后重试。可用 GET /bills 查账单。",
  "tags": [
    "分场与分镜"
  ],
  "responses": {
    "200": {
      "description": "单场重建分镜",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "taskId": {
                    "type": "string",
                    "description": "任务号。"
                  },
                  "type": {
                    "type": "string",
                    "description": "固定为 SHOTS_REBUILD。"
                  },
                  "status": {
                    "type": "string",
                    "description": "提交时固定为 QUEUED。"
                  },
                  "progress": {
                    "nullable": true
                  },
                  "result": {
                    "nullable": true
                  },
                  "error": {
                    "nullable": true
                  },
                  "cost": {
                    "nullable": true
                  },
                  "createdAt": {
                    "type": "string"
                  },
                  "finishedAt": {
                    "nullable": true
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "taskId": "tk_7Yp5Or2",
              "type": "SHOTS_REBUILD",
              "status": "QUEUED",
              "progress": null,
              "result": null,
              "error": null,
              "cost": null,
              "createdAt": "2026-09-16T09:30:00.000+08:00",
              "finishedAt": null
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "Idempotency-Key",
      "in": "header",
      "required": false,
      "description": "幂等键。",
      "schema": {
        "type": "string"
      }
    },
    {
      "name": "sceneId",
      "in": "path",
      "required": true,
      "description": "对外场次号。",
      "schema": {
        "type": "string"
      },
      "example": "sc_6Ym2Wq9"
    }
  ],
  "requestBody": {
    "required": false,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {}
        },
        "example": {}
      }
    }
  }
}
```

<a id="list-shots-by-episode"></a>

### GET /episodes/{episodeId}/shots - 镜头列表

Operation ID: `list-shots-by-episode`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=storyboard-list-shots-by-episode) | [Saved web text](web-pages/list-shots-by-episode.txt)

游标分页查询该集下的镜头。

Complete operation specification:

```json
{
  "operationId": "list-shots-by-episode",
  "summary": "镜头列表",
  "description": "游标分页查询该集下的镜头。",
  "tags": [
    "分场与分镜"
  ],
  "responses": {
    "200": {
      "description": "镜头列表",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "items": {
                    "type": "array",
                    "items": {
                      "type": "object",
                      "properties": {
                        "shotId": {
                          "type": "string"
                        },
                        "sceneId": {
                          "type": "string"
                        },
                        "shotIndex": {
                          "type": "number"
                        },
                        "sceneIndex": {
                          "type": "number"
                        },
                        "description": {
                          "type": "string"
                        },
                        "dialogue": {
                          "type": "string"
                        },
                        "durationSeconds": {
                          "type": "number"
                        },
                        "selectedImageUrl": {
                          "type": "string"
                        },
                        "selectedVideoUrl": {
                          "nullable": true
                        },
                        "status": {
                          "type": "string"
                        }
                      }
                    }
                  },
                  "nextCursor": {
                    "nullable": true
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "items": [
                {
                  "shotId": "sh_7Qz3Rk9",
                  "sceneId": "sc_6Ym2Wq9",
                  "shotIndex": 1,
                  "sceneIndex": 1,
                  "description": "雨中街道，林夏疾步奔跑，霓虹灯光倒映在积水中。",
                  "dialogue": "林夏（喘息）：不能再等了……",
                  "durationSeconds": 5,
                  "selectedImageUrl": "https://cos.runninghub.cn/aivideo/shot-image/xxx.png?sign=...",
                  "selectedVideoUrl": null,
                  "status": "READY"
                }
              ],
              "nextCursor": null
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "episodeId",
      "in": "path",
      "required": true,
      "description": "对外剧集号。",
      "schema": {
        "type": "string"
      },
      "example": "ep_4Rt7QxNp1"
    },
    {
      "name": "cursor",
      "in": "query",
      "required": false,
      "description": "游标，取上一页响应的 nextCursor。",
      "schema": {
        "type": "string"
      }
    },
    {
      "name": "limit",
      "in": "query",
      "required": false,
      "description": "每页条数，1~100，缺省 20，越界返回 422。",
      "schema": {
        "type": "integer"
      }
    }
  ]
}
```


<a id="group-10"></a>

## 镜头产出

<a id="generate-shot-image"></a>

### POST /shots/{shotId}/image-generations - 镜头生图

Operation ID: `generate-shot-image`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=shots-generate-shot-image) | [Saved web text](web-pages/generate-shot-image.txt)

为指定镜头生成故事板图，异步任务。

前置条件：镜头关联的角色 / 场景 / 道具至少要有一张资产图（先调用 POST /assets/{assetId}/image-generations），否则返回 409 DRAMA_STAGE_PRECONDITION。

新生成的图会自动成为当前选中（提交时即选中），体现为 GET /episodes/{episodeId}/shots 的 selectedImageUrl；PUT /shots/{shotId}/selected-image 用于在多个候选图间切换。

Complete operation specification:

```json
{
  "operationId": "generate-shot-image",
  "summary": "镜头生图",
  "description": "为指定镜头生成故事板图，异步任务。\n\n前置条件：镜头关联的角色 / 场景 / 道具至少要有一张资产图（先调用 POST /assets/{assetId}/image-generations），否则返回 409 DRAMA_STAGE_PRECONDITION。\n\n新生成的图会自动成为当前选中（提交时即选中），体现为 GET /episodes/{episodeId}/shots 的 selectedImageUrl；PUT /shots/{shotId}/selected-image 用于在多个候选图间切换。",
  "tags": [
    "镜头产出"
  ],
  "responses": {
    "200": {
      "description": "镜头生图",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "taskId": {
                    "type": "string",
                    "description": "任务号。"
                  },
                  "type": {
                    "type": "string",
                    "description": "固定为 SHOT_IMAGE_GENERATE。"
                  },
                  "status": {
                    "type": "string"
                  },
                  "progress": {
                    "nullable": true
                  },
                  "result": {
                    "nullable": true,
                    "description": "SUCCEEDED 后为 { imageUrl }。"
                  },
                  "error": {
                    "nullable": true
                  },
                  "cost": {
                    "nullable": true
                  },
                  "createdAt": {
                    "type": "string"
                  },
                  "finishedAt": {
                    "nullable": true
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "taskId": "tk_8Zq6Ps3",
              "type": "SHOT_IMAGE_GENERATE",
              "status": "QUEUED",
              "progress": null,
              "result": null,
              "error": null,
              "cost": null,
              "createdAt": "2026-09-16T09:35:00.000+08:00",
              "finishedAt": null
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "Idempotency-Key",
      "in": "header",
      "required": false,
      "description": "幂等键。",
      "schema": {
        "type": "string"
      }
    },
    {
      "name": "shotId",
      "in": "path",
      "required": true,
      "description": "对外镜头号。",
      "schema": {
        "type": "string"
      },
      "example": "sh_7Qz3Rk9"
    }
  ],
  "requestBody": {
    "required": true,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "appCode": {
              "type": "string",
              "description": "生图应用码，取自 GET /catalog/apps（capability=IMAGE）。分镜生图只接受 I2I 应用：NANO_PRO_G2_I2I_OFFICIAL、NANO_PRO_G2_I2I_LOW、NANO_PRO_I2I_OFFICIAL、NANO_PRO_I2I_LOW、NANO_V2_I2I_OFFICIAL、NANO_V2_I2I_LOW，传其它应用返回 400 DRAMA_REQUEST_FAILED。appCode 区分大小写。"
            },
            "prompt": {
              "type": "string",
              "description": "自定义提示词；不传则用后端默认拼装逻辑。"
            },
            "aspectRatio": {
              "type": "string",
              "description": "画幅比例，如 16:9；不受支持时回落默认档。"
            },
            "resolution": {
              "type": "string",
              "description": "分辨率；不受支持时回落默认档。"
            }
          },
          "required": [
            "appCode"
          ]
        },
        "example": {
          "appCode": "NANO_PRO_G2_I2I_OFFICIAL",
          "aspectRatio": "16:9"
        }
      }
    }
  }
}
```

<a id="generate-shot-video"></a>

### POST /shots/{shotId}/video-generations - 镜头生视频

Operation ID: `generate-shot-video`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=shots-generate-shot-video) | [Saved web text](web-pages/generate-shot-video.txt)

为指定镜头生成视频，异步任务。

任务在远端视频真正出片后才进入 SUCCEEDED，result 里带 videoUrl；提交成功但仍在生成时状态是 RUNNING，请勿把 RUNNING 当作完成。

新生成的视频会自动成为当前选中（完成时选中），体现为 GET /episodes/{episodeId}/shots 的 selectedVideoUrl；PUT /shots/{shotId}/selected-video 用于在多个候选视频间切换。

该模型对本团队的在跑任务数已满时，任务以 FAILED 结束且 error.code 为 DRAMA_MODEL_CONCURRENCY_LIMIT（未受理、未扣费），建议退避后重试。

Complete operation specification:

```json
{
  "operationId": "generate-shot-video",
  "summary": "镜头生视频",
  "description": "为指定镜头生成视频，异步任务。\n\n任务在远端视频真正出片后才进入 SUCCEEDED，result 里带 videoUrl；提交成功但仍在生成时状态是 RUNNING，请勿把 RUNNING 当作完成。\n\n新生成的视频会自动成为当前选中（完成时选中），体现为 GET /episodes/{episodeId}/shots 的 selectedVideoUrl；PUT /shots/{shotId}/selected-video 用于在多个候选视频间切换。\n\n该模型对本团队的在跑任务数已满时，任务以 FAILED 结束且 error.code 为 DRAMA_MODEL_CONCURRENCY_LIMIT（未受理、未扣费），建议退避后重试。",
  "tags": [
    "镜头产出"
  ],
  "responses": {
    "200": {
      "description": "镜头生视频",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "taskId": {
                    "type": "string",
                    "description": "任务号。"
                  },
                  "type": {
                    "type": "string",
                    "description": "固定为 SHOT_VIDEO_GENERATE。"
                  },
                  "status": {
                    "type": "string"
                  },
                  "progress": {
                    "nullable": true
                  },
                  "result": {
                    "nullable": true,
                    "description": "SUCCEEDED 后为该次生成的视频信息（videoId、url 等，具体字段以实际返回为准）。"
                  },
                  "error": {
                    "nullable": true
                  },
                  "cost": {
                    "nullable": true
                  },
                  "createdAt": {
                    "type": "string"
                  },
                  "finishedAt": {
                    "nullable": true
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "taskId": "tk_9As7Qt4",
              "type": "SHOT_VIDEO_GENERATE",
              "status": "QUEUED",
              "progress": null,
              "result": null,
              "error": null,
              "cost": null,
              "createdAt": "2026-09-16T09:40:00.000+08:00",
              "finishedAt": null
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "Idempotency-Key",
      "in": "header",
      "required": false,
      "description": "幂等键。",
      "schema": {
        "type": "string"
      }
    },
    {
      "name": "shotId",
      "in": "path",
      "required": true,
      "description": "对外镜头号。",
      "schema": {
        "type": "string"
      },
      "example": "sh_7Qz3Rk9"
    }
  ],
  "requestBody": {
    "required": true,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "appCode": {
              "type": "string",
              "description": "生视频应用码，取自 GET /catalog/apps（capability=VIDEO）。"
            },
            "modelParams": {
              "type": "object",
              "description": "模型参数覆盖，键对应应用 request_template 里的 fieldKey；最多 50 项，超出返回 422。"
            },
            "promptOverride": {
              "type": "string",
              "description": "自定义 prompt，非空时直发模型，跳过后端默认渲染。"
            },
            "referenceSourceVideoId": {
              "type": "string",
              "description": "续拍参考的同镜历史视频 id（vd_ 前缀），取自 GET /shots/{shotId}/videos 的 videoId。"
            }
          },
          "required": [
            "appCode"
          ]
        },
        "example": {
          "appCode": "SEEDANCE_2_FAST_MULTIMODAL_VIDEO",
          "modelParams": {
            "motionStrength": 0.6
          }
        }
      }
    }
  }
}
```

<a id="select-shot-image"></a>

### PUT /shots/{shotId}/selected-image - 选定镜头图

Operation ID: `select-shot-image`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=shots-select-shot-image) | [Saved web text](web-pages/select-shot-image.txt)

把某张候选图设为该镜头的当前选中图。

本接口不支持 Idempotency-Key；重复调用同一 imageId 是幂等的（结果不变）。

imageId 不属于路径里的镜头时返回 404 DRAMA_NOT_FOUND。

Complete operation specification:

```json
{
  "operationId": "select-shot-image",
  "summary": "选定镜头图",
  "description": "把某张候选图设为该镜头的当前选中图。\n\n本接口不支持 Idempotency-Key；重复调用同一 imageId 是幂等的（结果不变）。\n\nimageId 不属于路径里的镜头时返回 404 DRAMA_NOT_FOUND。",
  "tags": [
    "镜头产出"
  ],
  "responses": {
    "200": {
      "description": "选定镜头图",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "nullable": true
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": null
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "shotId",
      "in": "path",
      "required": true,
      "description": "对外镜头号。",
      "schema": {
        "type": "string"
      },
      "example": "sh_7Qz3Rk9"
    }
  ],
  "requestBody": {
    "required": true,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "imageId": {
              "type": "string",
              "description": "候选图 id（im_ 前缀），取自 GET /shots/{shotId}/images。"
            }
          },
          "required": [
            "imageId"
          ]
        },
        "example": {
          "imageId": "im_9Pq2Kd"
        }
      }
    }
  }
}
```

<a id="select-shot-video"></a>

### PUT /shots/{shotId}/selected-video - 选定镜头视频

Operation ID: `select-shot-video`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=shots-select-shot-video) | [Saved web text](web-pages/select-shot-video.txt)

把某个候选视频设为该镜头的当前选中视频。

videoId 不属于路径里的镜头时返回 404 DRAMA_NOT_FOUND。

Complete operation specification:

```json
{
  "operationId": "select-shot-video",
  "summary": "选定镜头视频",
  "description": "把某个候选视频设为该镜头的当前选中视频。\n\nvideoId 不属于路径里的镜头时返回 404 DRAMA_NOT_FOUND。",
  "tags": [
    "镜头产出"
  ],
  "responses": {
    "200": {
      "description": "选定镜头视频",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "nullable": true
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": null
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "shotId",
      "in": "path",
      "required": true,
      "description": "对外镜头号。",
      "schema": {
        "type": "string"
      },
      "example": "sh_7Qz3Rk9"
    }
  ],
  "requestBody": {
    "required": true,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "videoId": {
              "type": "string",
              "description": "候选视频 id（vd_ 前缀），取自 GET /shots/{shotId}/videos。"
            }
          },
          "required": [
            "videoId"
          ]
        },
        "example": {
          "videoId": "vd_4Wt6Ln"
        }
      }
    }
  }
}
```

<a id="list-shot-images"></a>

### GET /shots/{shotId}/images - 镜头图列表

Operation ID: `list-shot-images`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=shots-list-shot-images) | [Saved web text](web-pages/list-shot-images.txt)

查询该镜头下的全部候选图（不分页）。

Complete operation specification:

```json
{
  "operationId": "list-shot-images",
  "summary": "镜头图列表",
  "description": "查询该镜头下的全部候选图（不分页）。",
  "tags": [
    "镜头产出"
  ],
  "responses": {
    "200": {
      "description": "镜头图列表",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "array",
                "items": {
                  "type": "object",
                  "properties": {
                    "imageId": {
                      "type": "string",
                      "description": "对外图片号，im_ 前缀。"
                    },
                    "url": {
                      "type": "string",
                      "description": "可访问地址；尚未生成完成时可能为 null。"
                    },
                    "selected": {
                      "type": "boolean",
                      "description": "是否为当前选中图。"
                    },
                    "status": {
                      "type": "string",
                      "description": "生成状态。",
                      "enum": [
                        "PENDING",
                        "READY",
                        "FAILED"
                      ]
                    },
                    "createdAt": {
                      "type": "string",
                      "description": "ISO-8601 创建时间。"
                    }
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": [
              {
                "imageId": "im_9Pq2Kd",
                "url": "https://cos.runninghub.cn/aivideo/shot-image/xxx.png?sign=...",
                "selected": true,
                "status": "READY",
                "createdAt": "2026-09-16T09:36:00.000+08:00"
              }
            ]
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "shotId",
      "in": "path",
      "required": true,
      "description": "对外镜头号。",
      "schema": {
        "type": "string"
      },
      "example": "sh_7Qz3Rk9"
    }
  ]
}
```

<a id="list-shot-videos"></a>

### GET /shots/{shotId}/videos - 镜头视频列表

Operation ID: `list-shot-videos`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=shots-list-shot-videos) | [Saved web text](web-pages/list-shot-videos.txt)

查询该镜头下的全部候选视频（不分页）。

Complete operation specification:

```json
{
  "operationId": "list-shot-videos",
  "summary": "镜头视频列表",
  "description": "查询该镜头下的全部候选视频（不分页）。",
  "tags": [
    "镜头产出"
  ],
  "responses": {
    "200": {
      "description": "镜头视频列表",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "array",
                "items": {
                  "type": "object",
                  "properties": {
                    "videoId": {
                      "type": "string",
                      "description": "对外视频号，vd_ 前缀。可作为 generate-shot-video 的 referenceSourceVideoId 使用。"
                    },
                    "url": {
                      "type": "string",
                      "description": "可访问地址；尚未生成完成时可能为 null。"
                    },
                    "durationSeconds": {
                      "type": "number",
                      "description": "视频时长（秒）。"
                    },
                    "selected": {
                      "type": "boolean",
                      "description": "是否为当前选中视频。"
                    },
                    "status": {
                      "type": "string",
                      "description": "生成状态，如 GENERATING / DONE / FAILED。"
                    },
                    "createdAt": {
                      "type": "string",
                      "description": "ISO-8601 创建时间。"
                    }
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": [
              {
                "videoId": "vd_4Wt6Ln",
                "url": "https://cos.runninghub.cn/aivideo/shot-video/xxx.mp4?sign=...",
                "durationSeconds": 5.2,
                "selected": true,
                "status": "DONE",
                "createdAt": "2026-09-16T09:41:00.000+08:00"
              }
            ]
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "shotId",
      "in": "path",
      "required": true,
      "description": "对外镜头号。",
      "schema": {
        "type": "string"
      },
      "example": "sh_7Qz3Rk9"
    }
  ]
}
```

<a id="get-shot"></a>

### GET /shots/{shotId} - 查询镜头详情

Operation ID: `get-shot`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=shots-get-shot) | [Saved web text](web-pages/get-shot.txt)

按镜头号查询详情，字段同「镜头列表」。

不属于当前企业 Key 或 id 不合法都返回 404 DRAMA_NOT_FOUND。

Complete operation specification:

```json
{
  "operationId": "get-shot",
  "summary": "查询镜头详情",
  "description": "按镜头号查询详情，字段同「镜头列表」。\n\n不属于当前企业 Key 或 id 不合法都返回 404 DRAMA_NOT_FOUND。",
  "tags": [
    "镜头产出"
  ],
  "responses": {
    "200": {
      "description": "查询镜头详情",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "shotId": {
                    "type": "string",
                    "description": "对外镜头号。"
                  },
                  "sceneId": {
                    "type": "string",
                    "description": "所属场次号。"
                  },
                  "shotIndex": {
                    "type": "number",
                    "description": "镜头在场次内的序号（1 起，按顺序连续）。"
                  },
                  "sceneIndex": {
                    "type": "number",
                    "description": "所属场次的顺序号。"
                  },
                  "description": {
                    "type": "string",
                    "description": "画面描述纯文本。"
                  },
                  "dialogue": {
                    "type": "string",
                    "description": "台词纯文本，多段以换行分隔。"
                  },
                  "durationSeconds": {
                    "type": "number",
                    "description": "镜头时长（秒）。"
                  },
                  "selectedImageUrl": {
                    "type": "string",
                    "description": "当前选中故事板图的可访问地址；未生成或未选中为 null。"
                  },
                  "selectedVideoUrl": {
                    "nullable": true,
                    "description": "当前选中镜头视频的可访问地址；未生成或未选中为 null。"
                  },
                  "status": {
                    "type": "string",
                    "description": "优先级：选中的镜头视频状态 > 选中的故事板图状态 > PENDING。"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "shotId": "sh_7Qz3Rk9",
              "sceneId": "sc_6Ym2Wq9",
              "shotIndex": 1,
              "sceneIndex": 1,
              "description": "雨中街道，林夏疾步奔跑，霓虹灯光倒映在积水中。",
              "dialogue": "林夏（喘息）：不能再等了……",
              "durationSeconds": 5,
              "selectedImageUrl": "https://cos.runninghub.cn/aivideo/shot-image/xxx.png?sign=...",
              "selectedVideoUrl": null,
              "status": "READY"
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "shotId",
      "in": "path",
      "required": true,
      "description": "对外镜头号。",
      "schema": {
        "type": "string"
      },
      "example": "sh_7Qz3Rk9"
    }
  ]
}
```

<a id="patch-shot"></a>

### PATCH /shots/{shotId} - 更新镜头

Operation ID: `patch-shot`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=shots-patch-shot) | [Saved web text](web-pages/patch-shot.txt)

修改镜头的画面描述 / 台词 / 时长，字段为空不修改。

Complete operation specification:

```json
{
  "operationId": "patch-shot",
  "summary": "更新镜头",
  "description": "修改镜头的画面描述 / 台词 / 时长，字段为空不修改。",
  "tags": [
    "镜头产出"
  ],
  "responses": {
    "200": {
      "description": "更新镜头",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "shotId": {
                    "type": "string"
                  },
                  "sceneId": {
                    "type": "string"
                  },
                  "shotIndex": {
                    "type": "number"
                  },
                  "sceneIndex": {
                    "type": "number"
                  },
                  "description": {
                    "type": "string"
                  },
                  "dialogue": {
                    "type": "string"
                  },
                  "durationSeconds": {
                    "type": "number"
                  },
                  "selectedImageUrl": {
                    "nullable": true
                  },
                  "selectedVideoUrl": {
                    "nullable": true
                  },
                  "status": {
                    "type": "string"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "shotId": "sh_7Qz3Rk9",
              "sceneId": "sc_6Ym2Wq9",
              "shotIndex": 1,
              "sceneIndex": 1,
              "description": "雨中街道，林夏疾步奔跑，霓虹灯光倒映在积水中。",
              "dialogue": "林夏（喘息）：不能再等了……",
              "durationSeconds": 6,
              "selectedImageUrl": null,
              "selectedVideoUrl": null,
              "status": "PENDING"
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "shotId",
      "in": "path",
      "required": true,
      "description": "对外镜头号。",
      "schema": {
        "type": "string"
      },
      "example": "sh_7Qz3Rk9"
    }
  ],
  "requestBody": {
    "required": false,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "description": {
              "type": "string",
              "description": "新画面描述，不传则不改。"
            },
            "dialogue": {
              "type": "string",
              "description": "新台词，不传则不改。"
            },
            "durationSeconds": {
              "type": "integer",
              "description": "新镜头时长（秒），不传则不改。1~600 秒整数，越界返回 422。"
            }
          }
        },
        "example": {
          "durationSeconds": 6
        }
      }
    }
  }
}
```

<a id="delete-shot"></a>

### DELETE /shots/{shotId} - 删除镜头

Operation ID: `delete-shot`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=shots-delete-shot) | [Saved web text](web-pages/delete-shot.txt)

软删除一个镜头。

软删除，删除后无法恢复；已生成的故事板图 / 视频不会被清理，只是不再通过镜头列表看到。

Complete operation specification:

```json
{
  "operationId": "delete-shot",
  "summary": "删除镜头",
  "description": "软删除一个镜头。\n\n软删除，删除后无法恢复；已生成的故事板图 / 视频不会被清理，只是不再通过镜头列表看到。",
  "tags": [
    "镜头产出"
  ],
  "responses": {
    "200": {
      "description": "删除镜头",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "nullable": true
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": null
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "shotId",
      "in": "path",
      "required": true,
      "description": "对外镜头号。",
      "schema": {
        "type": "string"
      },
      "example": "sh_7Qz3Rk9"
    }
  ]
}
```

<a id="create-shot"></a>

### POST /scenes/{sceneId}/shots - 创建镜头

Operation ID: `create-shot`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=shots-create-shot) | [Saved web text](web-pages/create-shot.txt)

在指定场次下手动插入一个镜头。

afterShotId 不属于同一场次时返回 404 DRAMA_NOT_FOUND。

不支持 Idempotency-Key，重复提交会创建多个镜头。

Complete operation specification:

```json
{
  "operationId": "create-shot",
  "summary": "创建镜头",
  "description": "在指定场次下手动插入一个镜头。\n\nafterShotId 不属于同一场次时返回 404 DRAMA_NOT_FOUND。\n\n不支持 Idempotency-Key，重复提交会创建多个镜头。",
  "tags": [
    "镜头产出"
  ],
  "responses": {
    "200": {
      "description": "创建镜头",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "shotId": {
                    "type": "string",
                    "description": "对外镜头号。"
                  },
                  "sceneId": {
                    "type": "string",
                    "description": "所属场次号。"
                  },
                  "shotIndex": {
                    "type": "number",
                    "description": "镜头在场次内的序号（1 起，按顺序连续）。"
                  },
                  "sceneIndex": {
                    "type": "number",
                    "description": "所属场次的顺序号。"
                  },
                  "description": {
                    "type": "string",
                    "description": "画面描述。"
                  },
                  "dialogue": {
                    "nullable": true,
                    "description": "台词。"
                  },
                  "durationSeconds": {
                    "type": "number",
                    "description": "镜头时长（秒）。"
                  },
                  "selectedImageUrl": {
                    "nullable": true,
                    "description": "新建时恒为 null。"
                  },
                  "selectedVideoUrl": {
                    "nullable": true,
                    "description": "新建时恒为 null。"
                  },
                  "status": {
                    "type": "string",
                    "description": "新建时恒为 PENDING。"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "shotId": "sh_9Tv5Wx3",
              "sceneId": "sc_6Ym2Wq9",
              "shotIndex": 2,
              "sceneIndex": 1,
              "description": "林夏推开便利店的门，风铃作响。",
              "dialogue": null,
              "durationSeconds": 3,
              "selectedImageUrl": null,
              "selectedVideoUrl": null,
              "status": "PENDING"
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "sceneId",
      "in": "path",
      "required": true,
      "description": "对外场次号。",
      "schema": {
        "type": "string"
      },
      "example": "sc_6Ym2Wq9"
    }
  ],
  "requestBody": {
    "required": true,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "description": {
              "type": "string",
              "description": "画面描述。"
            },
            "dialogue": {
              "type": "string",
              "description": "台词，可空。"
            },
            "durationSeconds": {
              "type": "integer",
              "description": "镜头时长（秒），可空。1~600 秒整数，越界返回 422。"
            },
            "afterShotId": {
              "type": "string",
              "description": "插入锚点：新镜头紧跟该镜头之后（须同场次）；不传则追加到场次末尾。"
            }
          },
          "required": [
            "description"
          ]
        },
        "example": {
          "description": "林夏推开便利店的门，风铃作响。",
          "durationSeconds": 3
        }
      }
    }
  }
}
```

<a id="split-shot"></a>

### POST /shots/{shotId}/splits - 拆分镜头

Operation ID: `split-shot`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=shots-split-shot) | [Saved web text](web-pages/split-shot.txt)

把一个镜头按子镜头段位置拆成两个。

拆分会重置两个镜头已生成的故事板图 / 视频关联（新的正文需要重新生成产出）。

splitAt 不小于该镜头子镜头段数时返回 422。

Complete operation specification:

```json
{
  "operationId": "split-shot",
  "summary": "拆分镜头",
  "description": "把一个镜头按子镜头段位置拆成两个。\n\n拆分会重置两个镜头已生成的故事板图 / 视频关联（新的正文需要重新生成产出）。\n\nsplitAt 不小于该镜头子镜头段数时返回 422。",
  "tags": [
    "镜头产出"
  ],
  "responses": {
    "200": {
      "description": "拆分镜头",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "array",
                "items": {
                  "type": "object",
                  "properties": {
                    "shotId": {
                      "type": "string"
                    },
                    "sceneId": {
                      "type": "string"
                    },
                    "shotIndex": {
                      "type": "number"
                    },
                    "sceneIndex": {
                      "type": "number"
                    },
                    "description": {
                      "type": "string"
                    },
                    "dialogue": {
                      "type": "string"
                    },
                    "durationSeconds": {
                      "type": "number"
                    },
                    "selectedImageUrl": {
                      "nullable": true
                    },
                    "selectedVideoUrl": {
                      "nullable": true
                    },
                    "status": {
                      "type": "string"
                    }
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": [
              {
                "shotId": "sh_7Qz3Rk9",
                "sceneId": "sc_6Ym2Wq9",
                "shotIndex": 1,
                "sceneIndex": 1,
                "description": "雨中街道，林夏疾步奔跑，",
                "dialogue": "林夏（喘息）：不能再等了……",
                "durationSeconds": 3,
                "selectedImageUrl": null,
                "selectedVideoUrl": null,
                "status": "PENDING"
              },
              {
                "shotId": "sh_2Uw6Xy4",
                "sceneId": "sc_6Ym2Wq9",
                "shotIndex": 2,
                "sceneIndex": 1,
                "description": "霓虹灯光倒映在积水中。",
                "dialogue": null,
                "durationSeconds": 2,
                "selectedImageUrl": null,
                "selectedVideoUrl": null,
                "status": "PENDING"
              }
            ]
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "shotId",
      "in": "path",
      "required": true,
      "description": "对外镜头号。",
      "schema": {
        "type": "string"
      },
      "example": "sh_7Qz3Rk9"
    }
  ],
  "requestBody": {
    "required": false,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "splitAt": {
              "type": "integer",
              "description": "拆分位置：子镜头段索引（1 起），须小于该镜头子镜头段数，否则 422；省略则从中点拆分；单段镜头可省略。"
            }
          }
        },
        "example": {
          "splitAt": 12
        }
      }
    }
  }
}
```

<a id="merge-shots"></a>

### POST /shot-merges - 合并镜头

Operation ID: `merge-shots`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=shots-merge-shots) | [Saved web text](web-pages/merge-shots.txt)

把两个镜头合并为一个（第二个合入第一个）。

shotIds 数量不为 2，或任一 id 不合法 / 不属于当前 Key，分别返回 422 DRAMA_VALIDATION_FAILED / 404 DRAMA_NOT_FOUND；合并会重置已生成的故事板图 / 视频关联。

Complete operation specification:

```json
{
  "operationId": "merge-shots",
  "summary": "合并镜头",
  "description": "把两个镜头合并为一个（第二个合入第一个）。\n\nshotIds 数量不为 2，或任一 id 不合法 / 不属于当前 Key，分别返回 422 DRAMA_VALIDATION_FAILED / 404 DRAMA_NOT_FOUND；合并会重置已生成的故事板图 / 视频关联。",
  "tags": [
    "镜头产出"
  ],
  "responses": {
    "200": {
      "description": "合并镜头",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "shotId": {
                    "type": "string",
                    "description": "合并后仍存在的镜头号（即传入的第 1 个）。"
                  },
                  "sceneId": {
                    "type": "string"
                  },
                  "shotIndex": {
                    "type": "number"
                  },
                  "sceneIndex": {
                    "type": "number"
                  },
                  "description": {
                    "type": "string"
                  },
                  "dialogue": {
                    "type": "string"
                  },
                  "durationSeconds": {
                    "type": "number"
                  },
                  "selectedImageUrl": {
                    "nullable": true
                  },
                  "selectedVideoUrl": {
                    "nullable": true
                  },
                  "status": {
                    "type": "string"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "shotId": "sh_7Qz3Rk9",
              "sceneId": "sc_6Ym2Wq9",
              "shotIndex": 1,
              "sceneIndex": 1,
              "description": "雨中街道，林夏疾步奔跑，霓虹灯光倒映在积水中。",
              "dialogue": "林夏（喘息）：不能再等了……",
              "durationSeconds": 5,
              "selectedImageUrl": null,
              "selectedVideoUrl": null,
              "status": "PENDING"
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "requestBody": {
    "required": true,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "shotIds": {
              "type": "array",
              "items": {
                "type": "string"
              },
              "description": "必须正好传 2 个镜头号（数量不为 2 返回 422 DRAMA_VALIDATION_FAILED），第 2 个合入第 1 个；第 2 个镜头会被软删。"
            }
          },
          "required": [
            "shotIds"
          ]
        },
        "example": {
          "shotIds": [
            "sh_7Qz3Rk9",
            "sh_2Uw6Xy4"
          ]
        }
      }
    }
  }
}
```

<a id="move-shot"></a>

### PUT /shots/{shotId}/position - 移动镜头

Operation ID: `move-shot`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=shots-move-shot) | [Saved web text](web-pages/move-shot.txt)

把镜头移动到另一个场次（或同场次内的另一个位置）。

targetSceneId / afterShotId 不属于当前 Key 或不合法都返回 404 DRAMA_NOT_FOUND；afterShotId 不属于 targetSceneId 时同样按 404 处理。

Complete operation specification:

```json
{
  "operationId": "move-shot",
  "summary": "移动镜头",
  "description": "把镜头移动到另一个场次（或同场次内的另一个位置）。\n\ntargetSceneId / afterShotId 不属于当前 Key 或不合法都返回 404 DRAMA_NOT_FOUND；afterShotId 不属于 targetSceneId 时同样按 404 处理。",
  "tags": [
    "镜头产出"
  ],
  "responses": {
    "200": {
      "description": "移动镜头",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "shotId": {
                    "type": "string",
                    "description": "对外镜头号。"
                  },
                  "sceneId": {
                    "type": "string",
                    "description": "移动后所属的场次号。"
                  },
                  "shotIndex": {
                    "type": "number",
                    "description": "移动后在目标场次内的序号（1 起）。"
                  },
                  "sceneIndex": {
                    "type": "number"
                  },
                  "description": {
                    "type": "string"
                  },
                  "dialogue": {
                    "type": "string"
                  },
                  "durationSeconds": {
                    "type": "number"
                  },
                  "selectedImageUrl": {
                    "nullable": true
                  },
                  "selectedVideoUrl": {
                    "nullable": true
                  },
                  "status": {
                    "type": "string"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "shotId": "sh_7Qz3Rk9",
              "sceneId": "sc_8Pr4Ty6",
              "shotIndex": 1,
              "sceneIndex": 2,
              "description": "雨中街道，林夏疾步奔跑，霓虹灯光倒映在积水中。",
              "dialogue": "林夏（喘息）：不能再等了……",
              "durationSeconds": 5,
              "selectedImageUrl": null,
              "selectedVideoUrl": null,
              "status": "PENDING"
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "shotId",
      "in": "path",
      "required": true,
      "description": "对外镜头号。",
      "schema": {
        "type": "string"
      },
      "example": "sh_7Qz3Rk9"
    }
  ],
  "requestBody": {
    "required": true,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "targetSceneId": {
              "type": "string",
              "description": "目标场次号；传当前所在场次即为场内移动。"
            },
            "afterShotId": {
              "type": "string",
              "description": "落点锚点：移动到该镜头之后（须属于目标场次）；不传则移动到目标场次最前。"
            }
          },
          "required": [
            "targetSceneId"
          ]
        },
        "example": {
          "targetSceneId": "sc_8Pr4Ty6"
        }
      }
    }
  }
}
```

<a id="batch-update-shots"></a>

### PATCH /shots - 批量更新镜头

Operation ID: `batch-update-shots`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=shots-batch-update-shots) | [Saved web text](web-pages/batch-update-shots.txt)

一次提交多条镜头的字段更新，逐条应用；任一条 shotId 非法则整个请求以 422 / 404 终止，不做部分成功。

本接口是逐条串行调用「更新镜头」的等价封装，不是原子事务；某一项 shotId 不合法会导致整个请求报错终止（不是跳过），请确保 items 里每个 shotId 都合法且属于当前 Key。

Complete operation specification:

```json
{
  "operationId": "batch-update-shots",
  "summary": "批量更新镜头",
  "description": "一次提交多条镜头的字段更新，逐条应用；任一条 shotId 非法则整个请求以 422 / 404 终止，不做部分成功。\n\n本接口是逐条串行调用「更新镜头」的等价封装，不是原子事务；某一项 shotId 不合法会导致整个请求报错终止（不是跳过），请确保 items 里每个 shotId 都合法且属于当前 Key。",
  "tags": [
    "镜头产出"
  ],
  "responses": {
    "200": {
      "description": "批量更新镜头",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "array",
                "items": {
                  "type": "object",
                  "properties": {
                    "shotId": {
                      "type": "string"
                    },
                    "sceneId": {
                      "type": "string"
                    },
                    "shotIndex": {
                      "type": "number"
                    },
                    "sceneIndex": {
                      "type": "number"
                    },
                    "description": {
                      "type": "string"
                    },
                    "dialogue": {
                      "type": "string"
                    },
                    "durationSeconds": {
                      "type": "number"
                    },
                    "selectedImageUrl": {
                      "nullable": true
                    },
                    "selectedVideoUrl": {
                      "nullable": true
                    },
                    "status": {
                      "type": "string"
                    }
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": [
              {
                "shotId": "sh_7Qz3Rk9",
                "sceneId": "sc_6Ym2Wq9",
                "shotIndex": 1,
                "sceneIndex": 1,
                "description": "雨中街道，林夏疾步奔跑，霓虹灯光倒映在积水中。",
                "dialogue": "林夏（喘息）：不能再等了……",
                "durationSeconds": 4,
                "selectedImageUrl": null,
                "selectedVideoUrl": null,
                "status": "PENDING"
              }
            ]
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "requestBody": {
    "required": true,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "items": {
              "type": "array",
              "items": {
                "type": "object"
              },
              "description": "待更新镜头列表，最多 200 项（超出返回 422）；每项字段同「更新镜头」的请求体（外加必填的 shotId）。"
            },
            "items[].shotId": {
              "type": "string",
              "description": "对外镜头号。"
            },
            "items[].description": {
              "type": "string",
              "description": "新画面描述，不传则不改。"
            },
            "items[].dialogue": {
              "type": "string",
              "description": "新台词，不传则不改。"
            },
            "items[].durationSeconds": {
              "type": "integer",
              "description": "新镜头时长（秒），不传则不改。1~600 秒整数，越界返回 422。"
            }
          },
          "required": [
            "items",
            "items[].shotId"
          ]
        },
        "example": {
          "items": [
            {
              "shotId": "sh_7Qz3Rk9",
              "durationSeconds": 4
            },
            {
              "shotId": "sh_2Uw6Xy4",
              "dialogue": "（无台词）"
            }
          ]
        }
      }
    }
  }
}
```

<a id="reset-shot-narrative"></a>

### DELETE /shots/{shotId}/narrative-edits - 重置镜头叙事

Operation ID: `reset-shot-narrative`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=shots-reset-shot-narrative) | [Saved web text](web-pages/reset-shot-narrative.txt)

把镜头的画面描述 / 台词恢复到最近一次 AI 生成的原始版本，撤销后续的人工 / AI 改写。

该镜头没有可恢复的原始快照时（如老数据、或本来就是手动创建的镜头）返回 400 DRAMA_REQUEST_FAILED。

不可逆：恢复后无法再恢复到重置前的人工改写内容，请谨慎调用。

Complete operation specification:

```json
{
  "operationId": "reset-shot-narrative",
  "summary": "重置镜头叙事",
  "description": "把镜头的画面描述 / 台词恢复到最近一次 AI 生成的原始版本，撤销后续的人工 / AI 改写。\n\n该镜头没有可恢复的原始快照时（如老数据、或本来就是手动创建的镜头）返回 400 DRAMA_REQUEST_FAILED。\n\n不可逆：恢复后无法再恢复到重置前的人工改写内容，请谨慎调用。",
  "tags": [
    "镜头产出"
  ],
  "responses": {
    "200": {
      "description": "重置镜头叙事",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "shotId": {
                    "type": "string",
                    "description": "对外镜头号。"
                  },
                  "sceneId": {
                    "type": "string"
                  },
                  "shotIndex": {
                    "type": "number"
                  },
                  "sceneIndex": {
                    "type": "number"
                  },
                  "description": {
                    "type": "string",
                    "description": "恢复后的画面描述。"
                  },
                  "dialogue": {
                    "type": "string",
                    "description": "恢复后的台词。"
                  },
                  "durationSeconds": {
                    "type": "number"
                  },
                  "selectedImageUrl": {
                    "nullable": true
                  },
                  "selectedVideoUrl": {
                    "nullable": true
                  },
                  "status": {
                    "type": "string"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "shotId": "sh_7Qz3Rk9",
              "sceneId": "sc_6Ym2Wq9",
              "shotIndex": 1,
              "sceneIndex": 1,
              "description": "雨中街道，林夏疾步奔跑，霓虹灯光倒映在积水中。",
              "dialogue": "林夏（喘息）：不能再等了……",
              "durationSeconds": 5,
              "selectedImageUrl": null,
              "selectedVideoUrl": null,
              "status": "PENDING"
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "shotId",
      "in": "path",
      "required": true,
      "description": "对外镜头号。",
      "schema": {
        "type": "string"
      },
      "example": "sh_7Qz3Rk9"
    }
  ]
}
```


<a id="group-11"></a>

## 成片与文件

<a id="export-film"></a>

### POST /episodes/{episodeId}/films - 导出成片

Operation ID: `export-film`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=film-export-film) | [Saved web text](web-pages/export-film.txt)

把该集所有镜头视频拼接导出为一条完整成片，异步任务。

前置条件：该集至少有一个镜头已生成视频，否则返回 409 DRAMA_STAGE_PRECONDITION（极小概率的竞态场景会退化成 400 DRAMA_REQUEST_FAILED）。

同一集最多保留 10 条已导出（EXPORTED）记录，超出的旧记录会被自动淘汰，导出中 / 失败记录不参与淘汰计数。

Complete operation specification:

```json
{
  "operationId": "export-film",
  "summary": "导出成片",
  "description": "把该集所有镜头视频拼接导出为一条完整成片，异步任务。\n\n前置条件：该集至少有一个镜头已生成视频，否则返回 409 DRAMA_STAGE_PRECONDITION（极小概率的竞态场景会退化成 400 DRAMA_REQUEST_FAILED）。\n\n同一集最多保留 10 条已导出（EXPORTED）记录，超出的旧记录会被自动淘汰，导出中 / 失败记录不参与淘汰计数。",
  "tags": [
    "成片与文件"
  ],
  "responses": {
    "200": {
      "description": "导出成片",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "taskId": {
                    "type": "string",
                    "description": "任务号。"
                  },
                  "type": {
                    "type": "string",
                    "description": "固定为 FILM_EXPORT。"
                  },
                  "status": {
                    "type": "string"
                  },
                  "progress": {
                    "nullable": true
                  },
                  "result": {
                    "nullable": true,
                    "description": "SUCCEEDED 后为 { fileId, videoUrl }，videoUrl 是 24 小时有效的签名地址。"
                  },
                  "error": {
                    "nullable": true
                  },
                  "cost": {
                    "nullable": true
                  },
                  "createdAt": {
                    "type": "string"
                  },
                  "finishedAt": {
                    "nullable": true
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "taskId": "tk_1Bu8Rv5",
              "type": "FILM_EXPORT",
              "status": "QUEUED",
              "progress": null,
              "result": null,
              "error": null,
              "cost": null,
              "createdAt": "2026-09-16T09:50:00.000+08:00",
              "finishedAt": null
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "Idempotency-Key",
      "in": "header",
      "required": false,
      "description": "幂等键。",
      "schema": {
        "type": "string"
      }
    },
    {
      "name": "episodeId",
      "in": "path",
      "required": true,
      "description": "对外剧集号。",
      "schema": {
        "type": "string"
      },
      "example": "ep_4Rt7QxNp1"
    }
  ]
}
```

<a id="list-films"></a>

### GET /episodes/{episodeId}/films - 成片列表

Operation ID: `list-films`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=film-list-films) | [Saved web text](web-pages/list-films.txt)

查询该集全部成片记录（不分页）。

Complete operation specification:

```json
{
  "operationId": "list-films",
  "summary": "成片列表",
  "description": "查询该集全部成片记录（不分页）。",
  "tags": [
    "成片与文件"
  ],
  "responses": {
    "200": {
      "description": "成片列表",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "array",
                "items": {
                  "type": "object",
                  "properties": {
                    "fileId": {
                      "type": "string",
                      "description": "对外文件号，fl_ 前缀。"
                    },
                    "status": {
                      "type": "string",
                      "description": "导出状态。",
                      "enum": [
                        "EXPORTING",
                        "EXPORTED",
                        "FAILED"
                      ]
                    },
                    "videoUrl": {
                      "type": "string",
                      "description": "仅 status=EXPORTED 时非空，24 小时签名地址；过期后用 GET /files/{fileId}/url 重新获取。"
                    },
                    "createdAt": {
                      "type": "string",
                      "description": "ISO-8601 创建时间。"
                    }
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": [
              {
                "fileId": "fl_8Xr2Vb9",
                "status": "EXPORTED",
                "videoUrl": "https://cos.runninghub.cn/aivideo/film/xxx.mp4?sign=...",
                "createdAt": "2026-09-16T09:52:00.000+08:00"
              }
            ]
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "episodeId",
      "in": "path",
      "required": true,
      "description": "对外剧集号。",
      "schema": {
        "type": "string"
      },
      "example": "ep_4Rt7QxNp1"
    }
  ]
}
```

<a id="get-file-url"></a>

### GET /files/{fileId}/url - 重新获取文件地址

Operation ID: `get-file-url`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=film-get-file-url) | [Saved web text](web-pages/get-file-url.txt)

为过期的文件重新生成签名访问地址。

仅适用成片文件号（fl_ 前缀，来自 GET /episodes/{id}/films 等成片接口）；上传文件 up_ 不适用，传入返回 404。

文件尚未生成完成（如导出仍在进行）时返回 409 DRAMA_FILE_NOT_READY。

Complete operation specification:

```json
{
  "operationId": "get-file-url",
  "summary": "重新获取文件地址",
  "description": "为过期的文件重新生成签名访问地址。\n\n仅适用成片文件号（fl_ 前缀，来自 GET /episodes/{id}/films 等成片接口）；上传文件 up_ 不适用，传入返回 404。\n\n文件尚未生成完成（如导出仍在进行）时返回 409 DRAMA_FILE_NOT_READY。",
  "tags": [
    "成片与文件"
  ],
  "responses": {
    "200": {
      "description": "重新获取文件地址",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "fileId": {
                    "type": "string",
                    "description": "对外文件号。"
                  },
                  "url": {
                    "type": "string",
                    "description": "重新签名后的可访问地址。"
                  },
                  "expiresAt": {
                    "type": "string",
                    "description": "ISO-8601 过期时间，默认 24 小时后。"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "fileId": "fl_8Xr2Vb9",
              "url": "https://cos.runninghub.cn/aivideo/film/xxx.mp4?sign=...",
              "expiresAt": "2026-09-17T09:52:00.000+08:00"
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "fileId",
      "in": "path",
      "required": true,
      "description": "成片文件号（fl_ 前缀，来自 GET /episodes/{id}/films 等成片接口）；上传文件 up_ 不适用，传入返回 404。",
      "schema": {
        "type": "string"
      },
      "example": "fl_8Xr2Vb9"
    }
  ]
}
```


<a id="group-12"></a>

## 任务

<a id="get-task"></a>

### GET /tasks/{taskNo} - 查询任务

Operation ID: `get-task`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=tasks-get-task) | [Saved web text](web-pages/get-task.txt)

按任务号查询统一任务信封，是轮询产出的主要方式。

Complete operation specification:

```json
{
  "operationId": "get-task",
  "summary": "查询任务",
  "description": "按任务号查询统一任务信封，是轮询产出的主要方式。",
  "tags": [
    "任务"
  ],
  "responses": {
    "200": {
      "description": "查询任务",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "taskId": {
                    "type": "string",
                    "description": "对外任务号。"
                  },
                  "type": {
                    "type": "string",
                    "description": "任务类型，见“统一任务对象”说明。"
                  },
                  "status": {
                    "type": "string",
                    "description": "任务状态五值之一。"
                  },
                  "progress": {
                    "nullable": true,
                    "description": "一期恒为 null。"
                  },
                  "result": {
                    "type": "object",
                    "properties": {
                      "imageUrl": {
                        "type": "string"
                      }
                    },
                    "description": "仅 SUCCEEDED 非空。"
                  },
                  "error": {
                    "nullable": true,
                    "description": "仅 FAILED 非空，{ code, message }。"
                  },
                  "cost": {
                    "nullable": true,
                    "description": "一期恒为 null。"
                  },
                  "createdAt": {
                    "type": "string",
                    "description": "ISO-8601 创建时间。"
                  },
                  "finishedAt": {
                    "type": "string",
                    "description": "仅终态非空。"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "taskId": "tk_1Xh6Bs4Q",
              "type": "SHOT_IMAGE_GENERATE",
              "status": "SUCCEEDED",
              "progress": null,
              "result": {
                "imageUrl": "https://cos.runninghub.cn/aivideo/shot-image/xxx.png?sign=..."
              },
              "error": null,
              "cost": null,
              "createdAt": "2026-09-16T10:00:00.000+08:00",
              "finishedAt": "2026-09-16T10:00:45.000+08:00"
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "taskNo",
      "in": "path",
      "required": true,
      "description": "对外任务号。",
      "schema": {
        "type": "string"
      },
      "example": "tk_1Xh6Bs4Q"
    }
  ]
}
```

<a id="list-tasks"></a>

### GET /tasks - 任务列表

Operation ID: `list-tasks`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=tasks-list-tasks) | [Saved web text](web-pages/list-tasks.txt)

游标分页查询当前企业 Key 下的任务，可按状态 / 类型过滤。

Complete operation specification:

```json
{
  "operationId": "list-tasks",
  "summary": "任务列表",
  "description": "游标分页查询当前企业 Key 下的任务，可按状态 / 类型过滤。",
  "tags": [
    "任务"
  ],
  "responses": {
    "200": {
      "description": "任务列表",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "items": {
                    "type": "array",
                    "items": {
                      "type": "object",
                      "properties": {
                        "taskId": {
                          "type": "string"
                        },
                        "type": {
                          "type": "string"
                        },
                        "status": {
                          "type": "string"
                        },
                        "progress": {
                          "nullable": true
                        },
                        "result": {
                          "type": "object",
                          "properties": {
                            "imageUrl": {
                              "type": "string"
                            }
                          }
                        },
                        "error": {
                          "nullable": true
                        },
                        "cost": {
                          "nullable": true
                        },
                        "createdAt": {
                          "type": "string"
                        },
                        "finishedAt": {
                          "type": "string"
                        }
                      }
                    },
                    "description": "本页任务列表，元素结构同「查询任务」的 data。"
                  },
                  "nextCursor": {
                    "nullable": true,
                    "description": "下一页游标；为空表示没有下一页。"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "items": [
                {
                  "taskId": "tk_1Xh6Bs4Q",
                  "type": "SHOT_IMAGE_GENERATE",
                  "status": "SUCCEEDED",
                  "progress": null,
                  "result": {
                    "imageUrl": "https://cos.runninghub.cn/aivideo/shot-image/xxx.png?sign=..."
                  },
                  "error": null,
                  "cost": null,
                  "createdAt": "2026-09-16T10:00:00.000+08:00",
                  "finishedAt": "2026-09-16T10:00:45.000+08:00"
                }
              ],
              "nextCursor": null
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "status",
      "in": "query",
      "required": false,
      "description": "按状态过滤；不在枚举内的值返回 422 DRAMA_VALIDATION_FAILED。",
      "schema": {
        "type": "string",
        "enum": [
          "QUEUED",
          "RUNNING",
          "SUCCEEDED",
          "FAILED",
          "CANCELED"
        ]
      }
    },
    {
      "name": "type",
      "in": "query",
      "required": false,
      "description": "按任务类型过滤；不在枚举内的值返回 422 DRAMA_VALIDATION_FAILED。",
      "schema": {
        "type": "string",
        "enum": [
          "ASSET_EXTRACT",
          "STORYBOARD_GENERATE",
          "SHOTS_REBUILD",
          "SHOT_IMAGE_GENERATE",
          "SHOT_VIDEO_GENERATE",
          "ASSET_IMAGE_GENERATE",
          "FILM_EXPORT",
          "PROJECT_IMPORT",
          "PROJECT_GENERATE",
          "SCRIPT_REFINE",
          "SCENE_REFINE",
          "PROJECT_REEXTRACT",
          "ASSET_IMAGE_EDIT"
        ]
      }
    },
    {
      "name": "cursor",
      "in": "query",
      "required": false,
      "description": "游标，取上一页响应的 nextCursor。",
      "schema": {
        "type": "string"
      }
    },
    {
      "name": "limit",
      "in": "query",
      "required": false,
      "description": "每页条数，1~100，缺省 20，越界返回 422。",
      "schema": {
        "type": "integer"
      }
    }
  ]
}
```

<a id="cancel-task"></a>

### POST /tasks/{taskNo}/cancellations - 取消任务

Operation ID: `cancel-task`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=tasks-cancel-task) | [Saved web text](web-pages/cancel-task.txt)

取消一个尚未完成的任务；LLM 任务与生图 / 生视频任务均可取消。

LLM 阶段任务（提资产 / 生分镜 / 单场重建 / 单场润色 / 剧本润色 / 一键导入 / agent 生成 / 项目重提取，内部 refType=JOB）与生图 / 生视频 / 资产生图 / 资产改图任务（SHOT_IMAGE_GENERATE / SHOT_VIDEO_GENERATE / ASSET_IMAGE_GENERATE / ASSET_IMAGE_EDIT）均可取消。

任务已落终态（SUCCEEDED / FAILED / CANCELED）后再次调用本接口返回 409 DRAMA_TASK_CANCEL_UNSUPPORTED，不是幂等成功。

LLM 计费任务取消后按已消耗量结算账单（CHARGED_PARTIAL_CANCELED），不是全额免单：取消只停止后续处理，取消时仍在进行的模型调用照常计入，账单在任务实际停止后结算；生图 / 生视频任务取消不产生 GET /bills 账单（计费口径见对应生成接口备注）。

Complete operation specification:

```json
{
  "operationId": "cancel-task",
  "summary": "取消任务",
  "description": "取消一个尚未完成的任务；LLM 任务与生图 / 生视频任务均可取消。\n\nLLM 阶段任务（提资产 / 生分镜 / 单场重建 / 单场润色 / 剧本润色 / 一键导入 / agent 生成 / 项目重提取，内部 refType=JOB）与生图 / 生视频 / 资产生图 / 资产改图任务（SHOT_IMAGE_GENERATE / SHOT_VIDEO_GENERATE / ASSET_IMAGE_GENERATE / ASSET_IMAGE_EDIT）均可取消。\n\n任务已落终态（SUCCEEDED / FAILED / CANCELED）后再次调用本接口返回 409 DRAMA_TASK_CANCEL_UNSUPPORTED，不是幂等成功。\n\nLLM 计费任务取消后按已消耗量结算账单（CHARGED_PARTIAL_CANCELED），不是全额免单：取消只停止后续处理，取消时仍在进行的模型调用照常计入，账单在任务实际停止后结算；生图 / 生视频任务取消不产生 GET /bills 账单（计费口径见对应生成接口备注）。",
  "tags": [
    "任务"
  ],
  "responses": {
    "200": {
      "description": "取消任务",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "taskId": {
                    "type": "string",
                    "description": "对外任务号。"
                  },
                  "type": {
                    "type": "string"
                  },
                  "status": {
                    "type": "string",
                    "description": "取消成功后为 CANCELED。"
                  },
                  "progress": {
                    "nullable": true
                  },
                  "result": {
                    "nullable": true
                  },
                  "error": {
                    "nullable": true
                  },
                  "cost": {
                    "nullable": true
                  },
                  "createdAt": {
                    "type": "string"
                  },
                  "finishedAt": {
                    "type": "string"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "taskId": "tk_1Xh6Bs4Q",
              "type": "STORYBOARD_GENERATE",
              "status": "CANCELED",
              "progress": null,
              "result": null,
              "error": null,
              "cost": null,
              "createdAt": "2026-09-16T10:00:00.000+08:00",
              "finishedAt": "2026-09-16T10:01:20.000+08:00"
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "taskNo",
      "in": "path",
      "required": true,
      "description": "对外任务号。",
      "schema": {
        "type": "string"
      },
      "example": "tk_1Xh6Bs4Q"
    }
  ]
}
```


<a id="group-13"></a>

## 平台

<a id="retry-task"></a>

### POST /tasks/{taskNo}/retries - 重试任务

Operation ID: `retry-task`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=platform-retry-task) | [Saved web text](web-pages/retry-task.txt)

用原始请求重新提交一次，产生一个全新任务；不影响原任务的状态。

仅 SHOT_IMAGE_GENERATE / SHOT_VIDEO_GENERATE / ASSET_IMAGE_GENERATE 三种任务类型支持重试（只有这三类落库时记录了原始请求），且原任务须已是 FAILED / CANCELED；其余类型，或原任务仍在 QUEUED / RUNNING、已 SUCCEEDED，均返回 409 DRAMA_OPERATION_NOT_ALLOWED。

不支持 Idempotency-Key，每次调用都会产生一个全新任务，不做去重；原任务保留在 GET /tasks 里不变（不会被覆盖或删除）。

按原始请求重新校验一遍前置条件（如资产是否有默认变体、appCode 是否仍可用），原来能提交不代表这次重试一定能成功。

Complete operation specification:

```json
{
  "operationId": "retry-task",
  "summary": "重试任务",
  "description": "用原始请求重新提交一次，产生一个全新任务；不影响原任务的状态。\n\n仅 SHOT_IMAGE_GENERATE / SHOT_VIDEO_GENERATE / ASSET_IMAGE_GENERATE 三种任务类型支持重试（只有这三类落库时记录了原始请求），且原任务须已是 FAILED / CANCELED；其余类型，或原任务仍在 QUEUED / RUNNING、已 SUCCEEDED，均返回 409 DRAMA_OPERATION_NOT_ALLOWED。\n\n不支持 Idempotency-Key，每次调用都会产生一个全新任务，不做去重；原任务保留在 GET /tasks 里不变（不会被覆盖或删除）。\n\n按原始请求重新校验一遍前置条件（如资产是否有默认变体、appCode 是否仍可用），原来能提交不代表这次重试一定能成功。",
  "tags": [
    "平台"
  ],
  "responses": {
    "200": {
      "description": "重试任务",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "taskId": {
                    "type": "string",
                    "description": "新任务号，与传入的 taskNo 不同。"
                  },
                  "type": {
                    "type": "string",
                    "description": "与原任务相同的任务类型。"
                  },
                  "status": {
                    "type": "string",
                    "description": "提交时固定为 QUEUED。"
                  },
                  "progress": {
                    "nullable": true
                  },
                  "result": {
                    "nullable": true
                  },
                  "error": {
                    "nullable": true
                  },
                  "cost": {
                    "nullable": true
                  },
                  "createdAt": {
                    "type": "string"
                  },
                  "finishedAt": {
                    "nullable": true
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "taskId": "tk_7Hc2Kd5",
              "type": "SHOT_VIDEO_GENERATE",
              "status": "QUEUED",
              "progress": null,
              "result": null,
              "error": null,
              "cost": null,
              "createdAt": "2026-09-17T09:30:00.000+08:00",
              "finishedAt": null
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "taskNo",
      "in": "path",
      "required": true,
      "description": "要重试的对外任务号。",
      "schema": {
        "type": "string"
      },
      "example": "tk_9As7Qt4"
    }
  ]
}
```

<a id="batch-generate-shot-images"></a>

### POST /episodes/{episodeId}/shot-image-generations - 批量镜头生图

Operation ID: `batch-generate-shot-images`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=platform-batch-generate-shot-images) | [Saved web text](web-pages/batch-generate-shot-images.txt)

对该集多个镜头批量提交生图任务，单镜失败不中断整批。

不支持 Idempotency-Key；每个镜头内部都是单独提交，等价于对每个镜头分别调用「镜头生图」，不做整批幂等。

shotIds 不传时会先翻页读出该集全部镜头（可能有上百个），耗时随镜头数增长，请预留足够的请求超时时间。

Complete operation specification:

```json
{
  "operationId": "batch-generate-shot-images",
  "summary": "批量镜头生图",
  "description": "对该集多个镜头批量提交生图任务，单镜失败不中断整批。\n\n不支持 Idempotency-Key；每个镜头内部都是单独提交，等价于对每个镜头分别调用「镜头生图」，不做整批幂等。\n\nshotIds 不传时会先翻页读出该集全部镜头（可能有上百个），耗时随镜头数增长，请预留足够的请求超时时间。",
  "tags": [
    "平台"
  ],
  "responses": {
    "200": {
      "description": "批量镜头生图",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "groupId": {
                    "type": "string",
                    "description": "本批次任务组号，用 GET /task-groups/{groupId} 一次性查询整批状态，无需对 taskIds 逐个轮询。"
                  },
                  "taskIds": {
                    "type": "array",
                    "items": {
                      "type": "string"
                    },
                    "description": "成功提交的任务号列表，与「镜头生图」返回的单任务号同构，可逐个用 GET /tasks/{taskNo} 轮询。"
                  },
                  "skipped": {
                    "type": "array",
                    "items": {
                      "type": "object",
                      "properties": {
                        "shotId": {
                          "type": "string"
                        },
                        "code": {
                          "type": "string"
                        },
                        "message": {
                          "type": "string"
                        }
                      }
                    },
                    "description": "被跳过的镜头列表，每项含 shotId、错误码 code、错误说明 message；不存在或不属于该集的 shotId 也会出现在这里（code=DRAMA_NOT_FOUND）。"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "groupId": "gr_9Xq2Ld7",
              "taskIds": [
                "tk_8Zq6Ps3",
                "tk_1Kf3Lm9"
              ],
              "skipped": [
                {
                  "shotId": "sh_2Uw6Xy4",
                  "code": "DRAMA_STAGE_PRECONDITION",
                  "message": "镜头关联的角色 / 场景 / 道具尚无形象图"
                }
              ]
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "episodeId",
      "in": "path",
      "required": true,
      "description": "对外剧集号。",
      "schema": {
        "type": "string"
      },
      "example": "ep_4Rt7QxNp1"
    }
  ],
  "requestBody": {
    "required": true,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "appCode": {
              "type": "string",
              "description": "生图应用码，取自 GET /catalog/apps（capability=IMAGE），要求同「镜头生图」（I2I 应用）。"
            },
            "aspectRatio": {
              "type": "string",
              "description": "画幅比例；不受支持时回落默认档。"
            },
            "shotIds": {
              "type": "array",
              "items": {
                "type": "string"
              },
              "description": "指定要生图的镜头号列表，最多 200 项（超出返回 422）；不传或空数组表示对该集全部镜头逐一生图。"
            }
          },
          "required": [
            "appCode"
          ]
        },
        "example": {
          "appCode": "NANO_PRO_G2_I2I_OFFICIAL",
          "aspectRatio": "16:9"
        }
      }
    }
  }
}
```

<a id="batch-generate-shot-videos"></a>

### POST /episodes/{episodeId}/shot-video-generations - 批量镜头生视频

Operation ID: `batch-generate-shot-videos`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=platform-batch-generate-shot-videos) | [Saved web text](web-pages/batch-generate-shot-videos.txt)

对该集多个镜头批量提交生视频任务，单镜失败不中断整批。

其余行为（无 Idempotency-Key、shotIds 为空时全量翻页）同「批量镜头生图」。

Complete operation specification:

```json
{
  "operationId": "batch-generate-shot-videos",
  "summary": "批量镜头生视频",
  "description": "对该集多个镜头批量提交生视频任务，单镜失败不中断整批。\n\n其余行为（无 Idempotency-Key、shotIds 为空时全量翻页）同「批量镜头生图」。",
  "tags": [
    "平台"
  ],
  "responses": {
    "200": {
      "description": "批量镜头生视频",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "groupId": {
                    "type": "string",
                    "description": "本批次任务组号，字段含义同「批量镜头生图」。"
                  },
                  "taskIds": {
                    "type": "array",
                    "items": {
                      "type": "string"
                    },
                    "description": "成功提交的任务号列表，与「镜头生视频」返回的单任务号同构。"
                  },
                  "skipped": {
                    "type": "array",
                    "items": {},
                    "description": "被跳过的镜头列表，字段结构同「批量镜头生图」。"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "groupId": "gr_9Xq2Ld7",
              "taskIds": [
                "tk_9As7Qt4"
              ],
              "skipped": []
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "episodeId",
      "in": "path",
      "required": true,
      "description": "对外剧集号。",
      "schema": {
        "type": "string"
      },
      "example": "ep_4Rt7QxNp1"
    }
  ],
  "requestBody": {
    "required": true,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "appCode": {
              "type": "string",
              "description": "生视频应用码，取自 GET /catalog/apps（capability=VIDEO）。"
            },
            "modelParams": {
              "type": "object",
              "description": "模型参数覆盖，键对应应用 request_template 里的 fieldKey，应用到批次内每一个镜头；最多 50 项，超出返回 422。"
            },
            "shotIds": {
              "type": "array",
              "items": {
                "type": "string"
              },
              "description": "指定要生视频的镜头号列表，最多 200 项（超出返回 422）；不传或空数组表示对该集全部镜头逐一生视频。"
            }
          },
          "required": [
            "appCode"
          ]
        },
        "example": {
          "appCode": "SEEDANCE_2_FAST_MULTIMODAL_VIDEO",
          "modelParams": {
            "motionStrength": 0.6
          }
        }
      }
    }
  }
}
```

<a id="get-task-group"></a>

### GET /task-groups/{groupId} - 查询批次任务组

Operation ID: `get-task-group`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=platform-get-task-group) | [Saved web text](web-pages/get-task-group.txt)

一次性查询「批量镜头生图 / 生视频」提交的整批任务状态，无需对 taskIds 逐个轮询。

items 内的每个任务与用 GET /tasks/{taskNo} 单独查询完全一致；本接口只是把整批状态一次性返回，省去对 taskIds 逐个轮询。

groupId 不存在或不属于当前企业 Key 返回 404 DRAMA_NOT_FOUND。

Complete operation specification:

```json
{
  "operationId": "get-task-group",
  "summary": "查询批次任务组",
  "description": "一次性查询「批量镜头生图 / 生视频」提交的整批任务状态，无需对 taskIds 逐个轮询。\n\nitems 内的每个任务与用 GET /tasks/{taskNo} 单独查询完全一致；本接口只是把整批状态一次性返回，省去对 taskIds 逐个轮询。\n\ngroupId 不存在或不属于当前企业 Key 返回 404 DRAMA_NOT_FOUND。",
  "tags": [
    "平台"
  ],
  "responses": {
    "200": {
      "description": "查询批次任务组",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "groupId": {
                    "type": "string",
                    "description": "对外任务组号。"
                  },
                  "total": {
                    "type": "number",
                    "description": "该批次任务总数。"
                  },
                  "counts": {
                    "type": "object",
                    "properties": {
                      "QUEUED": {
                        "type": "string"
                      },
                      "RUNNING": {
                        "type": "string"
                      },
                      "SUCCEEDED": {
                        "type": "string"
                      },
                      "FAILED": {
                        "type": "string"
                      },
                      "CANCELED": {
                        "type": "string"
                      }
                    },
                    "description": "按状态统计的任务数，QUEUED / RUNNING / SUCCEEDED / FAILED / CANCELED 五个键恒定存在；各值为 64 位整数，以数字字符串返回，可能为 \"0\"。"
                  },
                  "items": {
                    "type": "array",
                    "items": {
                      "type": "object",
                      "properties": {
                        "taskId": {
                          "type": "string"
                        },
                        "type": {
                          "type": "string"
                        },
                        "status": {
                          "type": "string"
                        },
                        "progress": {
                          "nullable": true
                        },
                        "result": {
                          "type": "object",
                          "properties": {
                            "imageUrl": {
                              "type": "string"
                            }
                          }
                        },
                        "error": {
                          "nullable": true
                        },
                        "cost": {
                          "nullable": true
                        },
                        "createdAt": {
                          "type": "string"
                        },
                        "finishedAt": {
                          "type": "string"
                        }
                      }
                    },
                    "description": "批次内每个任务的完整任务对象，元素结构同「查询任务」的 data，顺序与提交时一致。"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "groupId": "gr_9Xq2Ld7",
              "total": 2,
              "counts": {
                "QUEUED": "0",
                "RUNNING": "1",
                "SUCCEEDED": "1",
                "FAILED": "0",
                "CANCELED": "0"
              },
              "items": [
                {
                  "taskId": "tk_8Zq6Ps3",
                  "type": "SHOT_IMAGE_GENERATE",
                  "status": "SUCCEEDED",
                  "progress": null,
                  "result": {
                    "imageUrl": "https://cos.runninghub.cn/aivideo/shot-image/xxx.png?sign=..."
                  },
                  "error": null,
                  "cost": null,
                  "createdAt": "2026-09-16T10:00:00.000+08:00",
                  "finishedAt": "2026-09-16T10:00:45.000+08:00"
                },
                {
                  "taskId": "tk_1Kf3Lm9",
                  "type": "SHOT_IMAGE_GENERATE",
                  "status": "RUNNING",
                  "progress": null,
                  "result": null,
                  "error": null,
                  "cost": null,
                  "createdAt": "2026-09-16T10:00:01.000+08:00",
                  "finishedAt": null
                }
              ]
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "groupId",
      "in": "path",
      "required": true,
      "description": "批量提交接口返回的任务组号。",
      "schema": {
        "type": "string"
      },
      "example": "gr_9Xq2Ld7"
    }
  ]
}
```

<a id="get-usage"></a>

### GET /usage - 用量查询

Operation ID: `get-usage`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=platform-get-usage) | [Saved web text](web-pages/get-usage.txt)

按天或按阶段汇总 LLM 阶段账单用量。

只统计状态为 CHARGED / CHARGED_PARTIAL_CANCELED 的 LLM 计费账单（同 GET /bills 的数据源），欠费账单（ARREARS / ARREARS_PARTIAL_CANCELED）补扣成功前不计入；生图 / 生视频计费不在这里体现。

from 晚于 to、查询跨度超过 92 天、日期格式非法，或 groupBy 不是 day / stage，均返回 422 DRAMA_VALIDATION_FAILED。

Complete operation specification:

```json
{
  "operationId": "get-usage",
  "summary": "用量查询",
  "description": "按天或按阶段汇总 LLM 阶段账单用量。\n\n只统计状态为 CHARGED / CHARGED_PARTIAL_CANCELED 的 LLM 计费账单（同 GET /bills 的数据源），欠费账单（ARREARS / ARREARS_PARTIAL_CANCELED）补扣成功前不计入；生图 / 生视频计费不在这里体现。\n\nfrom 晚于 to、查询跨度超过 92 天、日期格式非法，或 groupBy 不是 day / stage，均返回 422 DRAMA_VALIDATION_FAILED。",
  "tags": [
    "平台"
  ],
  "responses": {
    "200": {
      "description": "用量查询",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "from": {
                    "type": "string",
                    "description": "回显的起始日期。"
                  },
                  "to": {
                    "type": "string",
                    "description": "回显的结束日期。"
                  },
                  "groupBy": {
                    "type": "string",
                    "description": "回显的分组维度。"
                  },
                  "items": {
                    "type": "array",
                    "items": {
                      "type": "object",
                      "properties": {
                        "key": {
                          "type": "string",
                          "description": "分组键，见上。"
                        },
                        "taskCount": {
                          "type": "string",
                          "description": "该分组内的账单行数（近似任务数）；64 位整数以数字字符串返回。"
                        },
                        "inputTokens": {
                          "type": "string",
                          "description": "输入 token 总数；64 位整数以数字字符串返回。"
                        },
                        "outputTokens": {
                          "type": "string",
                          "description": "输出 token 总数；64 位整数以数字字符串返回。"
                        },
                        "amount": {
                          "type": "number",
                          "description": "实付金额合计。"
                        },
                        "currency": {
                          "type": "string",
                          "description": "币种；该分组无任何行时为 null。"
                        }
                      }
                    },
                    "description": "按 groupBy 分组的明细：groupBy=day 时 key 是 YYYY-MM-DD 日期字符串，groupBy=stage 时 key 是计费任务类型（ASSET_EXTRACT / STORYBOARD_GENERATE / SHOTS_REBUILD / PROJECT_IMPORT / PROJECT_GENERATE / SCRIPT_REFINE / SCENE_REFINE / PROJECT_REEXTRACT，与 GET /bills 的 stage 一致）。"
                  },
                  "total": {
                    "type": "object",
                    "properties": {
                      "key": {
                        "nullable": true
                      },
                      "taskCount": {
                        "type": "string"
                      },
                      "inputTokens": {
                        "type": "string"
                      },
                      "outputTokens": {
                        "type": "string"
                      },
                      "amount": {
                        "type": "number"
                      },
                      "currency": {
                        "type": "string"
                      }
                    },
                    "description": "整个查询区间的汇总行，字段结构同 items 元素，key 恒为 null。"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "from": "2026-08-19",
              "to": "2026-09-17",
              "groupBy": "stage",
              "items": [
                {
                  "key": "ASSET_EXTRACT",
                  "taskCount": "12",
                  "inputTokens": "218400",
                  "outputTokens": "50520",
                  "amount": 8.16,
                  "currency": "USD"
                },
                {
                  "key": "STORYBOARD_GENERATE",
                  "taskCount": "5",
                  "inputTokens": "96000",
                  "outputTokens": "21000",
                  "amount": 3.4,
                  "currency": "USD"
                }
              ],
              "total": {
                "key": null,
                "taskCount": "17",
                "inputTokens": "314400",
                "outputTokens": "71520",
                "amount": 11.56,
                "currency": "USD"
              }
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "from",
      "in": "query",
      "required": false,
      "description": "起始日期（含），格式 YYYY-MM-DD；不传按 to 往前推 29 天。",
      "schema": {
        "type": "string"
      },
      "example": "2026-08-19"
    },
    {
      "name": "to",
      "in": "query",
      "required": false,
      "description": "结束日期（含），格式 YYYY-MM-DD；不传按今天。",
      "schema": {
        "type": "string"
      },
      "example": "2026-09-17"
    },
    {
      "name": "groupBy",
      "in": "query",
      "required": false,
      "description": "分组维度；不传按 day，不是 day / stage 返回 422 DRAMA_VALIDATION_FAILED。",
      "schema": {
        "type": "string",
        "enum": [
          "day",
          "stage"
        ]
      }
    }
  ]
}
```

<a id="get-balance"></a>

### GET /balance - 余额查询

Operation ID: `get-balance`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=platform-get-balance) | [Saved web text](web-pages/get-balance.txt)

查询当前可用于本 API 消费的钱包余额。

企业 Key 挂团队时查团队钱包的可消费余额（受限来源已排除）；不挂团队（个人 / 企业主体）时查企业账户余额。两种口径都与提交任务时的余额门禁一致。

本接口从不返回非 200 的余额相关错误码；读取异常一律降级为 balance=null + message 说明，请按 balance 是否为 null 判断成败，不要假设 HTTP 状态会变化。

Complete operation specification:

```json
{
  "operationId": "get-balance",
  "summary": "余额查询",
  "description": "查询当前可用于本 API 消费的钱包余额。\n\n企业 Key 挂团队时查团队钱包的可消费余额（受限来源已排除）；不挂团队（个人 / 企业主体）时查企业账户余额。两种口径都与提交任务时的余额门禁一致。\n\n本接口从不返回非 200 的余额相关错误码；读取异常一律降级为 balance=null + message 说明，请按 balance 是否为 null 判断成败，不要假设 HTTP 状态会变化。",
  "tags": [
    "平台"
  ],
  "responses": {
    "200": {
      "description": "余额查询",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "balance": {
                    "type": "number",
                    "description": "可用余额，单位：元；读取失败或账户不存在时为 null，此时请看 message。"
                  },
                  "currency": {
                    "type": "string",
                    "description": "币种，国内站恒为 CNY；balance 为 null 时同为 null。"
                  },
                  "message": {
                    "nullable": true,
                    "description": "仅 balance 为 null 时非空，说明读取失败或账户不存在的原因。"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "balance": 128.5,
              "currency": "CNY",
              "message": null
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  }
}
```

<a id="get-quota"></a>

### GET /quota - 配额查询

Operation ID: `get-quota`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=platform-get-quota) | [Saved web text](web-pages/get-quota.txt)

查询当前企业 Key 的消费配额、并发上限与限流参数。

quotaLimit 为 null 的企业 Key 不受配额门禁限制，但仍受 concurrentLimit 与 rateLimit 约束。

Complete operation specification:

```json
{
  "operationId": "get-quota",
  "summary": "配额查询",
  "description": "查询当前企业 Key 的消费配额、并发上限与限流参数。\n\nquotaLimit 为 null 的企业 Key 不受配额门禁限制，但仍受 concurrentLimit 与 rateLimit 约束。",
  "tags": [
    "平台"
  ],
  "responses": {
    "200": {
      "description": "配额查询",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "quotaLimit": {
                    "type": "number",
                    "description": "配额上限；为 null 表示不限额。"
                  },
                  "quotaUsed": {
                    "type": "number",
                    "description": "已消费配额。"
                  },
                  "quotaRemaining": {
                    "type": "number",
                    "description": "剩余配额；quotaLimit 为 null（不限额）时本字段同为 null。"
                  },
                  "currency": {
                    "type": "string",
                    "description": "币种，国内站 CNY、海外站 USD。"
                  },
                  "concurrentLimit": {
                    "type": "number",
                    "description": "LLM 计费任务（提资产 / 分镜 / 单场重建 / 导入 / 生成 / 润色 / 场次改写 / 重提取）的并发上限，对应企业 Key 配置，超出返回 429 DRAMA_CONCURRENCY_LIMIT；生图 / 生视频 / 导出不占用。"
                  },
                  "rateLimit": {
                    "type": "object",
                    "properties": {
                      "replenishRatePerSecond": {
                        "type": "number",
                        "description": "每秒补充的令牌数。"
                      },
                      "burstCapacity": {
                        "type": "number",
                        "description": "令牌桶容量，即突发请求上限。"
                      }
                    },
                    "description": "令牌桶限流参数，与 GET /capabilities 返回的 rateLimit 一致。"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "quotaLimit": 1000,
              "quotaUsed": 12.5,
              "quotaRemaining": 987.5,
              "currency": "CNY",
              "concurrentLimit": 100,
              "rateLimit": {
                "replenishRatePerSecond": 20,
                "burstCapacity": 40
              }
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  }
}
```


<a id="group-14"></a>

## 计费

<a id="list-bills"></a>

### GET /bills - 账单列表

Operation ID: `list-bills`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=billing-list-bills) | [Saved web text](web-pages/list-bills.txt)

游标分页查询当前企业 Key 下的 LLM 阶段账单。

生图 / 生视频不走本账单体系，按 openapi 现有计价结算，这里查不到。

Complete operation specification:

```json
{
  "operationId": "list-bills",
  "summary": "账单列表",
  "description": "游标分页查询当前企业 Key 下的 LLM 阶段账单。\n\n生图 / 生视频不走本账单体系，按 openapi 现有计价结算，这里查不到。",
  "tags": [
    "计费"
  ],
  "responses": {
    "200": {
      "description": "账单列表",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "items": {
                    "type": "array",
                    "items": {
                      "type": "object",
                      "properties": {
                        "billNo": {
                          "type": "string"
                        },
                        "taskId": {
                          "type": "string"
                        },
                        "stage": {
                          "type": "string"
                        },
                        "model": {
                          "type": "string"
                        },
                        "inputTokens": {
                          "type": "string"
                        },
                        "outputTokens": {
                          "type": "string"
                        },
                        "amount": {
                          "type": "number"
                        },
                        "currency": {
                          "type": "string"
                        },
                        "status": {
                          "type": "string"
                        },
                        "createdAt": {
                          "type": "string"
                        },
                        "chargedAt": {
                          "type": "string"
                        }
                      }
                    }
                  },
                  "nextCursor": {
                    "nullable": true
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "items": [
                {
                  "billNo": "bl_3Cf8Rm7",
                  "taskId": "tk_1Xh6Bs4Q",
                  "stage": "ASSET_EXTRACT",
                  "model": "platform",
                  "inputTokens": "18320",
                  "outputTokens": "4210",
                  "amount": 0.68,
                  "currency": "USD",
                  "status": "CHARGED",
                  "createdAt": "2026-09-16T09:10:00.000+08:00",
                  "chargedAt": "2026-09-16T09:11:20.000+08:00"
                }
              ],
              "nextCursor": null
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "cursor",
      "in": "query",
      "required": false,
      "description": "游标，取上一页响应的 nextCursor。",
      "schema": {
        "type": "string"
      }
    },
    {
      "name": "limit",
      "in": "query",
      "required": false,
      "description": "每页条数，1~100，缺省 20，越界返回 422。",
      "schema": {
        "type": "integer"
      }
    }
  ]
}
```

<a id="get-bill"></a>

### GET /bills/{billNo} - 查询账单

Operation ID: `get-bill`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=billing-get-bill) | [Saved web text](web-pages/get-bill.txt)

按账单号查询详情。

Complete operation specification:

```json
{
  "operationId": "get-bill",
  "summary": "查询账单",
  "description": "按账单号查询详情。",
  "tags": [
    "计费"
  ],
  "responses": {
    "200": {
      "description": "查询账单",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "billNo": {
                    "type": "string",
                    "description": "对外账单号。"
                  },
                  "taskId": {
                    "type": "string",
                    "description": "关联的对外任务号。"
                  },
                  "stage": {
                    "type": "string",
                    "description": "阶段类型。"
                  },
                  "model": {
                    "type": "string",
                    "description": "固定为 platform，见账单列表。"
                  },
                  "inputTokens": {
                    "type": "string",
                    "description": "输入 token 数（数字字符串）；结算前为 null。"
                  },
                  "outputTokens": {
                    "type": "string",
                    "description": "输出 token 数（数字字符串）；结算前为 null。"
                  },
                  "amount": {
                    "type": "number",
                    "description": "结算金额（按分四舍五入，即实际扣款额；欠费状态为待补扣金额）；结算前为 null。"
                  },
                  "currency": {
                    "type": "string",
                    "description": "币种。"
                  },
                  "status": {
                    "type": "string",
                    "description": "账单状态：ESTIMATED 任务已受理、尚未结算；CHARGED 已全额扣款；NO_CHARGE_FAILED 任务失败、不扣费；CHARGED_PARTIAL_CANCELED 任务取消、已按已消耗量扣款；ARREARS / ARREARS_PARTIAL_CANCELED 结算时因系统原因扣款失败、欠费待补扣，由平台自动补扣，成功后分别转 CHARGED / CHARGED_PARTIAL_CANCELED。",
                    "enum": [
                      "ESTIMATED",
                      "CHARGED",
                      "NO_CHARGE_FAILED",
                      "CHARGED_PARTIAL_CANCELED",
                      "ARREARS",
                      "ARREARS_PARTIAL_CANCELED"
                    ]
                  },
                  "createdAt": {
                    "type": "string",
                    "description": "ISO-8601 创建时间。"
                  },
                  "chargedAt": {
                    "type": "string",
                    "description": "ISO-8601 结算时间；未结算为 null。"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "billNo": "bl_3Cf8Rm7",
              "taskId": "tk_1Xh6Bs4Q",
              "stage": "ASSET_EXTRACT",
              "model": "platform",
              "inputTokens": "18320",
              "outputTokens": "4210",
              "amount": 0.68,
              "currency": "USD",
              "status": "CHARGED",
              "createdAt": "2026-09-16T09:10:00.000+08:00",
              "chargedAt": "2026-09-16T09:11:20.000+08:00"
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "billNo",
      "in": "path",
      "required": true,
      "description": "对外账单号。",
      "schema": {
        "type": "string"
      },
      "example": "bl_3Cf8Rm7"
    }
  ]
}
```


<a id="group-15"></a>

## Webhook 管理

<a id="create-webhook"></a>

### POST /webhooks - 登记回调地址

Operation ID: `create-webhook`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=webhooks-create-webhook) | [Saved web text](web-pages/create-webhook.txt)

登记一个接收任务终态与账单事件的回调地址。

每个企业 Key 最多登记 5 条，超出返回 400 DRAMA_REQUEST_FAILED；url 不是公网 https 地址返回 422 DRAMA_VALIDATION_FAILED（见 url 参数说明）。

每次投递前会再校验一次目标地址是否仍为公网地址（防 DNS 重绑定），解析到内网地址的投递会直接按失败处理。

Complete operation specification:

```json
{
  "operationId": "create-webhook",
  "summary": "登记回调地址",
  "description": "登记一个接收任务终态与账单事件的回调地址。\n\n每个企业 Key 最多登记 5 条，超出返回 400 DRAMA_REQUEST_FAILED；url 不是公网 https 地址返回 422 DRAMA_VALIDATION_FAILED（见 url 参数说明）。\n\n每次投递前会再校验一次目标地址是否仍为公网地址（防 DNS 重绑定），解析到内网地址的投递会直接按失败处理。",
  "tags": [
    "Webhook 管理"
  ],
  "responses": {
    "200": {
      "description": "登记回调地址",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "webhookId": {
                    "type": "string",
                    "description": "对外回调登记号，wh_ 前缀。"
                  },
                  "url": {
                    "type": "string",
                    "description": "回调地址。"
                  },
                  "events": {
                    "type": "array",
                    "items": {
                      "type": "string"
                    },
                    "description": "订阅的事件类型；空数组代表全订阅。"
                  },
                  "secret": {
                    "type": "string",
                    "description": "签名密钥，仅本次创建响应明文返回，请立即保存。64 位十六进制字符串。"
                  },
                  "status": {
                    "type": "string",
                    "description": "状态，新建恒为 ENABLED。",
                    "enum": [
                      "ENABLED",
                      "DISABLED"
                    ]
                  },
                  "createdAt": {
                    "type": "string",
                    "description": "ISO-8601 创建时间。"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "webhookId": "wh_2Tq8Ln5",
              "url": "https://api.example.com/webhooks/runninghub",
              "events": [
                "task.succeeded",
                "task.failed"
              ],
              "secret": "3f9a1c7e2b5d4680f1a2b3c4d5e6f7081920a3b4c5d6e7f8091a2b3c4d5e6f7",
              "status": "ENABLED",
              "createdAt": "2026-09-16T09:00:00.000+08:00"
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "requestBody": {
    "required": true,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "url": {
              "type": "string",
              "description": "回调地址，必须是可公网访问的 https 地址（长度不超过 2048）：非 https、带用户名密码、主机名无法解析，或指向 localhost / 内网 / 回环 / 链路本地等非公网地址，均返回 422 DRAMA_VALIDATION_FAILED。"
            },
            "events": {
              "type": "array",
              "items": {
                "type": "string"
              },
              "description": "订阅的事件类型；留空或传空数组表示订阅全部事件类型。仅允许上述 4 个事件，含未知事件返回 422；最多 10 项，超出同样返回 422。"
            }
          },
          "required": [
            "url"
          ]
        },
        "example": {
          "url": "https://api.example.com/webhooks/runninghub",
          "events": [
            "task.succeeded",
            "task.failed"
          ]
        }
      }
    }
  }
}
```

<a id="list-webhooks"></a>

### GET /webhooks - 回调地址列表

Operation ID: `list-webhooks`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=webhooks-list-webhooks) | [Saved web text](web-pages/list-webhooks.txt)

查询当前企业 Key 下登记的全部回调地址（不分页）。

Complete operation specification:

```json
{
  "operationId": "list-webhooks",
  "summary": "回调地址列表",
  "description": "查询当前企业 Key 下登记的全部回调地址（不分页）。",
  "tags": [
    "Webhook 管理"
  ],
  "responses": {
    "200": {
      "description": "回调地址列表",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "array",
                "items": {
                  "type": "object",
                  "properties": {
                    "webhookId": {
                      "type": "string",
                      "description": "对外回调登记号。"
                    },
                    "url": {
                      "type": "string",
                      "description": "回调地址。"
                    },
                    "events": {
                      "type": "array",
                      "items": {
                        "type": "string"
                      },
                      "description": "订阅的事件类型。"
                    },
                    "secret": {
                      "type": "string",
                      "description": "脱敏后的签名密钥（前 8 位加四个星号），不是完整密钥；完整密钥只在创建响应里出现过一次。"
                    },
                    "status": {
                      "type": "string",
                      "description": "状态。",
                      "enum": [
                        "ENABLED",
                        "DISABLED"
                      ]
                    },
                    "createdAt": {
                      "type": "string",
                      "description": "ISO-8601 创建时间。"
                    }
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": [
              {
                "webhookId": "wh_2Tq8Ln5",
                "url": "https://api.example.com/webhooks/runninghub",
                "events": [
                  "task.succeeded",
                  "task.failed"
                ],
                "secret": "3f9a1c7e****",
                "status": "ENABLED",
                "createdAt": "2026-09-16T09:00:00.000+08:00"
              }
            ]
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  }
}
```

<a id="delete-webhook"></a>

### DELETE /webhooks/{webhookId} - 删除回调地址

Operation ID: `delete-webhook`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=webhooks-delete-webhook) | [Saved web text](web-pages/delete-webhook.txt)

硬删除一条回调登记。

硬删除后，已入队但还没投递成功的事件不会被清理，下一次尝试投递发现找不到 webhook 会直接判 DEAD，不影响任务 / 账单本身的状态。

Complete operation specification:

```json
{
  "operationId": "delete-webhook",
  "summary": "删除回调地址",
  "description": "硬删除一条回调登记。\n\n硬删除后，已入队但还没投递成功的事件不会被清理，下一次尝试投递发现找不到 webhook 会直接判 DEAD，不影响任务 / 账单本身的状态。",
  "tags": [
    "Webhook 管理"
  ],
  "responses": {
    "200": {
      "description": "删除回调地址",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "nullable": true
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": null
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "webhookId",
      "in": "path",
      "required": true,
      "description": "对外回调登记号。",
      "schema": {
        "type": "string"
      },
      "example": "wh_2Tq8Ln5"
    }
  ]
}
```

<a id="test-webhook"></a>

### POST /webhooks/{webhookId}/test-deliveries - 发送测试事件

Operation ID: `test-webhook`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=webhooks-test-webhook) | [Saved web text](web-pages/test-webhook.txt)

立即投递一条 webhook.test 事件，用于验证签名校验与网络连通性。

不受该 webhook 的 events 订阅过滤限制，即使只订阅了 bill.charged 也会收到这条测试事件。

Complete operation specification:

```json
{
  "operationId": "test-webhook",
  "summary": "发送测试事件",
  "description": "立即投递一条 webhook.test 事件，用于验证签名校验与网络连通性。\n\n不受该 webhook 的 events 订阅过滤限制，即使只订阅了 bill.charged 也会收到这条测试事件。",
  "tags": [
    "Webhook 管理"
  ],
  "responses": {
    "200": {
      "description": "发送测试事件",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "nullable": true
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": null
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "webhookId",
      "in": "path",
      "required": true,
      "description": "对外回调登记号。",
      "schema": {
        "type": "string"
      },
      "example": "wh_2Tq8Ln5"
    }
  ]
}
```

<a id="list-webhook-deliveries"></a>

### GET /webhooks/{webhookId}/deliveries - 投递记录列表

Operation ID: `list-webhook-deliveries`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=webhooks-list-webhook-deliveries) | [Saved web text](web-pages/list-webhook-deliveries.txt)

游标分页查询某个回调地址的历史投递记录。

DEAD 状态代表 5 级退避重试全部用完仍失败，或投递时发现 webhook 已被删除 / 签名密钥缺失等永久性错误，不会再自动重试；可用「手动重投」接口重新触发一次。

Complete operation specification:

```json
{
  "operationId": "list-webhook-deliveries",
  "summary": "投递记录列表",
  "description": "游标分页查询某个回调地址的历史投递记录。\n\nDEAD 状态代表 5 级退避重试全部用完仍失败，或投递时发现 webhook 已被删除 / 签名密钥缺失等永久性错误，不会再自动重试；可用「手动重投」接口重新触发一次。",
  "tags": [
    "Webhook 管理"
  ],
  "responses": {
    "200": {
      "description": "投递记录列表",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "items": {
                    "type": "array",
                    "items": {
                      "type": "object",
                      "properties": {
                        "deliveryId": {
                          "type": "string",
                          "description": "投递记录号，dl_ 前缀。"
                        },
                        "eventId": {
                          "type": "string",
                          "description": "关联的事件 id，同信封字段 eventId。"
                        },
                        "eventType": {
                          "type": "string",
                          "description": "事件类型。"
                        },
                        "status": {
                          "type": "string",
                          "description": "投递状态：PENDING 等待投递 / 等待退避重试，SENDING 正在发送，DELIVERED 已成功送达（收到 2xx），DEAD 重试用尽或永久性失败、不再自动重试。",
                          "enum": [
                            "PENDING",
                            "SENDING",
                            "DELIVERED",
                            "DEAD"
                          ]
                        },
                        "attempts": {
                          "type": "number",
                          "description": "已尝试投递次数；手动重投会把它归零后重新计数。"
                        },
                        "lastHttpStatus": {
                          "type": "number",
                          "description": "最近一次投递收到的 HTTP 状态码；从未投递过时为 null。"
                        },
                        "lastError": {
                          "nullable": true,
                          "description": "最近一次投递失败的错误说明；成功时为 null。"
                        },
                        "nextRetryAt": {
                          "nullable": true,
                          "description": "下次投递时间；status=PENDING 时非空，其余状态为 null。"
                        },
                        "createdAt": {
                          "type": "string",
                          "description": "事件产生时间。"
                        },
                        "updatedAt": {
                          "type": "string",
                          "description": "投递记录最近更新时间。"
                        }
                      }
                    },
                    "description": "本页投递记录列表。"
                  },
                  "nextCursor": {
                    "nullable": true,
                    "description": "下一页游标；为空表示没有下一页。"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "items": [
                {
                  "deliveryId": "dl_4Kp9Qw2",
                  "eventId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab",
                  "eventType": "task.succeeded",
                  "status": "DELIVERED",
                  "attempts": 1,
                  "lastHttpStatus": 200,
                  "lastError": null,
                  "nextRetryAt": null,
                  "createdAt": "2026-09-16T10:00:46.000+08:00",
                  "updatedAt": "2026-09-16T10:00:47.000+08:00"
                }
              ],
              "nextCursor": null
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "webhookId",
      "in": "path",
      "required": true,
      "description": "对外回调登记号。",
      "schema": {
        "type": "string"
      },
      "example": "wh_2Tq8Ln5"
    },
    {
      "name": "cursor",
      "in": "query",
      "required": false,
      "description": "游标，取上一页响应的 nextCursor。",
      "schema": {
        "type": "string"
      }
    },
    {
      "name": "limit",
      "in": "query",
      "required": false,
      "description": "每页条数，1~100，缺省 20，越界返回 422。",
      "schema": {
        "type": "integer"
      }
    }
  ]
}
```

<a id="redeliver-webhook-delivery"></a>

### POST /webhooks/{webhookId}/deliveries/{deliveryId}/redeliveries - 手动重投

Operation ID: `redeliver-webhook-delivery`

[Official documentation](https://story.runninghub.ai/zh-cn/ai-comic/open-api?doc=webhooks-redeliver-webhook-delivery) | [Saved web text](web-pages/redeliver-webhook-delivery.txt)

对一条投递记录立即触发一次重新投递。

不受 events 订阅过滤限制；webhookId 或 deliveryId 不存在、或不属于当前企业 Key，返回 404 DRAMA_NOT_FOUND。

DELIVERED 与 DEAD 状态的投递都可以重投（语义是“再送一次”）；投递正在发送中（SENDING）时返回 409 DRAMA_OPERATION_NOT_ALLOWED，稍后再试。重投是同步执行的：响应返回时本次投递已完成，attempts 归零重计为 1，失败则按退避表重新开始自动重试。

Complete operation specification:

```json
{
  "operationId": "redeliver-webhook-delivery",
  "summary": "手动重投",
  "description": "对一条投递记录立即触发一次重新投递。\n\n不受 events 订阅过滤限制；webhookId 或 deliveryId 不存在、或不属于当前企业 Key，返回 404 DRAMA_NOT_FOUND。\n\nDELIVERED 与 DEAD 状态的投递都可以重投（语义是“再送一次”）；投递正在发送中（SENDING）时返回 409 DRAMA_OPERATION_NOT_ALLOWED，稍后再试。重投是同步执行的：响应返回时本次投递已完成，attempts 归零重计为 1，失败则按退避表重新开始自动重试。",
  "tags": [
    "Webhook 管理"
  ],
  "responses": {
    "200": {
      "description": "手动重投",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "required": [
              "code",
              "msg",
              "data"
            ],
            "properties": {
              "code": {
                "type": "integer",
                "example": 0,
                "description": "固定为 0"
              },
              "msg": {
                "type": "string",
                "example": "success",
                "description": "固定为 success"
              },
              "errorMessages": {
                "nullable": true,
                "description": "恒为 null"
              },
              "data": {
                "type": "object",
                "properties": {
                  "deliveryId": {
                    "type": "string",
                    "description": "投递记录号。"
                  },
                  "eventId": {
                    "type": "string",
                    "description": "关联的事件 id。"
                  },
                  "eventType": {
                    "type": "string",
                    "description": "事件类型。"
                  },
                  "status": {
                    "type": "string",
                    "description": "本次重投后的投递状态：成功为 DELIVERED，失败则进入 PENDING 等待退避重试。",
                    "enum": [
                      "PENDING",
                      "SENDING",
                      "DELIVERED",
                      "DEAD"
                    ]
                  },
                  "attempts": {
                    "type": "number",
                    "description": "已尝试投递次数。重投时归零重新计数，本次重投完成后为 1，并从退避表第一级重新开始退避。"
                  },
                  "lastHttpStatus": {
                    "type": "number",
                    "description": "最近一次投递收到的 HTTP 状态码。"
                  },
                  "lastError": {
                    "type": "string",
                    "description": "最近一次投递失败的错误说明；成功时为 null。"
                  },
                  "nextRetryAt": {
                    "type": "string",
                    "description": "下次投递时间；status=PENDING 时非空，其余状态为 null。"
                  },
                  "createdAt": {
                    "type": "string",
                    "description": "事件产生时间。"
                  },
                  "updatedAt": {
                    "type": "string",
                    "description": "投递记录最近更新时间。"
                  }
                }
              }
            }
          },
          "example": {
            "code": 0,
            "msg": "success",
            "errorMessages": null,
            "data": {
              "deliveryId": "dl_4Kp9Qw2",
              "eventId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab",
              "eventType": "task.succeeded",
              "status": "PENDING",
              "attempts": 1,
              "lastHttpStatus": 500,
              "lastError": "connect timeout",
              "nextRetryAt": "2026-09-16T10:06:12.000+08:00",
              "createdAt": "2026-09-16T10:00:46.000+08:00",
              "updatedAt": "2026-09-16T10:05:12.000+08:00"
            }
          }
        }
      }
    },
    "default": {
      "description": "错误响应",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ErrorResponse"
          },
          "example": {
            "code": "DRAMA_BALANCE_INSUFFICIENT",
            "message": "余额不足，请充值后重试",
            "requestId": "a1b2c3d4-5e6f-4a1b-9c2d-1234567890ab"
          }
        }
      }
    }
  },
  "parameters": [
    {
      "name": "webhookId",
      "in": "path",
      "required": true,
      "description": "对外回调登记号。",
      "schema": {
        "type": "string"
      },
      "example": "wh_2Tq8Ln5"
    },
    {
      "name": "deliveryId",
      "in": "path",
      "required": true,
      "description": "对外投递记录号。",
      "schema": {
        "type": "string"
      },
      "example": "dl_4Kp9Qw2"
    }
  ]
}
```

