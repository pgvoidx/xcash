# xcash EVM Payment Collector Contracts

CREATE2 一次性 collector 的链上合约与编译产出。

## 设计

参见 [../../../docs/superpowers/specs/2026-05-16-evm-payment-collector-contracts-design.md](../../../docs/superpowers/specs/2026-05-16-evm-payment-collector-contracts-design.md)。

## 构建

```bash
forge install foundry-rs/forge-std --no-commit
make all
make test
```

`make build-yul` 需要 `solc 0.8.24`。如果默认 `solc` 不是 0.8.24，通过
`SOLC=/path/to/solc-0.8.24 make build-yul` 指定；版本不匹配会直接失败，
避免不同编译器输出导致 CREATE2 地址漂移。

## 地址预测公式

```text
collector = keccak256(0xff || factory || salt || keccak256(init_code))[-20:]
```

其中 `init_code` 由 `xcash/evm/contracts_codec.py` 的
`build_collector_init_code(to, token)` 生成。

## Sentinel 约定

| 占位符 | hex（20 字节） | 含义 |
|---|---|---|
| `VAULT_SENTINEL` | `deadbeefdeadbeefdeadbeefdeadbeefdeadbeef` | 归集目的地址 |
| `TOKEN_SENTINEL` | `cafebabecafebabecafebabecafebabecafebabe` | ERC20 代币地址（仅 ERC20Collector） |

Python 侧 patch 时必须校验模板中每个应出现的 sentinel 恰好出现 1 次。

## Salt 约束

工厂无访问控制，任何人拿到相同 `salt + init_code` 都能触发部署。业务层生成
salt 时必须包含服务端秘密或使用内部不可预测随机源，禁止直接使用公开订单号、
商户号、递增编号等可预测输入。

## artifacts

- `artifacts/*.bin` 由 `make build` 产出，Python `contracts_codec.py` 与 Foundry 测试都会读取。
- 任何对 `src/*.yul` 或 `src/PaymentCollectorFactory.sol` 的改动都需要 `make all` 重新生成 artifacts 并提交。
