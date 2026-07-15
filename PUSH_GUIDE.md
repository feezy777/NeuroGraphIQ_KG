# Git Push 指南

推送前确保 **Clash Verge 已开启系统代理**。

## 一键推送

```bash
cd D:\Tool\Coding\IDE\PyCharm\NeuroGraphIQ_KG_V3_1
git push origin main
```

## 底层原理（万一出问题排查用）

### SSH 代理配置

SSH 通过 Clash HTTP 代理 (`127.0.0.1:7897`) 连接 GitHub，配置文件：`~/.ssh/config`

```
Host github.com
  HostName ssh.github.com
  Port 443
  User git
  IdentityFile C:\Users\Administrator\.ssh\id_ed25519_neurograph
  IdentitiesOnly yes
  ProxyCommand connect -H 127.0.0.1:7897 %h %p
```

### SSH 密钥

| 文件 | 用途 | 状态 |
|------|------|------|
| `~/.ssh/id_ed25519_neurograph` | **当前使用的私钥** | ✅ 正常 |
| `~/.ssh/id_ed25519_neurograph.pub` | 对应公钥，已添加至 GitHub | ✅ 已授权 |
| `~/.ssh/id_ed25519` | 私钥已损坏（内容是 fingerprint，非真实密钥） | ❌ 勿用 |

### 远端仓库

```
git@github.com:feezy777/NeuroGraphIQ_KG.git
```
