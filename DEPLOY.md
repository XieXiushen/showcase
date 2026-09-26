# 部署说明

站点是纯静态 HTML，仓库根目录即站点根。以下两条路径都不需要买域名、不需要备案。

## 方式一：GitHub Pages（当前生效）

- 仓库：`XieXiushen/showcase`，分支 `main`，路径 `/`
- 开启方式（Dashboard）：Settings → Pages → Source = Deploy from a branch → `main` / `(root)`
- 等价 CLI：`gh api -X POST /repos/XieXiushen/showcase/pages -f "source[branch]=main" -f "source[path]=/"`
- 固定地址：`https://xiexiushen.github.io/showcase/`（每次 push 自动重建）

## 方式二：Cloudflare Pages（`<project>.pages.dev` 固定地址）

前置：一个免费 Cloudflare 账号，以及以下任一种授权方式：

1. API Token（权限 `Account → Cloudflare Pages → Edit`）导出为 `CLOUDFLARE_API_TOKEN`；或
2. 交互式 `npx wrangler login`。

完成后：

```bash
npx wrangler pages project create showcase-site --production-branch main
npx wrangler pages deploy . --project-name showcase-site --branch main
```

或走 Dashboard：Workers & Pages → Create → Pages → Connect to Git → 选择本仓库，构建命令留空、输出目录填 `/`，此后 push 自动重建。地址形如 `https://showcase-site.pages.dev`。

线上无构建产物需要维护，Pages 为纯静态托管，不依赖任何常开主机。
