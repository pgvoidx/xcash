SOLC ?= solc
FORGE ?= forge

.PHONY: all build build-yul build-sol test clean fixtures

all: build fixtures

build: build-yul build-sol

build-yul:
	@$(SOLC) --version | grep -q "Version: 0.8.24" || \
		(echo "build-yul requires solc 0.8.24; set SOLC=/path/to/solc-0.8.24" >&2; exit 1)
	@mkdir -p artifacts
	$(SOLC) --strict-assembly --bin --optimize --optimize-runs=200 src/NativeCollector.yul \
		| awk '/Binary representation:/{flag=1;next} flag{printf "0x%s", $$0;exit}' > artifacts/NativeCollector.bin
	$(SOLC) --strict-assembly --bin --optimize --optimize-runs=200 src/ERC20Collector.yul \
		| awk '/Binary representation:/{flag=1;next} flag{printf "0x%s", $$0;exit}' > artifacts/ERC20Collector.bin
	@test -s artifacts/NativeCollector.bin
	@test -s artifacts/ERC20Collector.bin

build-sol:
	$(FORGE) build --skip yul
	@mkdir -p artifacts
	@cp out/PaymentCollectorFactory.sol/PaymentCollectorFactory.json artifacts/PaymentCollectorFactory.json
	@python3 -c "import json; d=json.load(open('artifacts/PaymentCollectorFactory.json')); print(d['bytecode']['object'][2:])" > artifacts/PaymentCollectorFactory.bin
	@python3 -c "import json; d=json.load(open('artifacts/PaymentCollectorFactory.json')); print(json.dumps(d['abi'], indent=2, ensure_ascii=False))" > artifacts/PaymentCollectorFactory.abi.json

test:
	$(FORGE) test --skip yul -vvv

fixtures: build-yul
	@mkdir -p ../tests/fixtures
	$(FORGE) script scripts/DumpFixtures.s.sol --tc DumpFixtures

clean:
	rm -rf out/ cache/ artifacts/*.bin artifacts/*.json
