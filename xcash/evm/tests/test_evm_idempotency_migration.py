import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from web3 import Web3


@pytest.mark.django_db(transaction=True)
def test_unbroadcast_duplicate_groups_are_marked_dropped_before_constraints():
    executor = MigrationExecutor(connection)
    target_before = _targets_with_evm(
        executor,
        "0006_alter_contractdeploycollection_failure_reason_and_more",
    )
    executor.migrate(target_before)
    old_apps = executor.loader.project_state(target_before).apps

    chain = _create_minimal_chain(old_apps, suffix="idem-clean")
    crypto = _create_minimal_crypto(old_apps, suffix="idem-clean")
    address = _create_minimal_address(old_apps, suffix="idem-clean")

    x402_keep = _create_x402(
        old_apps,
        chain=chain,
        crypto=crypto,
        address=address,
        nonce=b"\x11" * 32,
    )
    x402_drop = _create_x402(
        old_apps,
        chain=chain,
        crypto=crypto,
        address=address,
        nonce=b"\x11" * 32,
    )
    create2_salt_keep = _create_create2(
        old_apps,
        chain=chain,
        crypto=crypto,
        address=address,
        salt=b"\x21" * 32,
        collector_suffix="22",
    )
    create2_salt_drop = _create_create2(
        old_apps,
        chain=chain,
        crypto=crypto,
        address=address,
        salt=b"\x21" * 32,
        collector_suffix="23",
    )
    create2_collector_keep = _create_create2(
        old_apps,
        chain=chain,
        crypto=crypto,
        address=address,
        salt=b"\x24" * 32,
        collector_suffix="25",
    )
    create2_collector_drop = _create_create2(
        old_apps,
        chain=chain,
        crypto=crypto,
        address=address,
        salt=b"\x26" * 32,
        collector_suffix="25",
    )

    executor = MigrationExecutor(connection)
    target_after = _targets_with_evm(
        executor,
        "0007_evm_idempotency_constraints",
    )
    executor.migrate(target_after)
    new_apps = executor.loader.project_state(target_after).apps
    x402_model = new_apps.get_model("evm", "X402Facilitation")
    create2_model = new_apps.get_model("evm", "ContractDeployCollection")

    assert x402_model.objects.get(pk=x402_keep.pk).status == "created"
    x402_later = x402_model.objects.get(pk=x402_drop.pk)
    assert x402_later.status == "dropped"
    assert x402_later.failure_reason == ""

    assert create2_model.objects.get(pk=create2_salt_keep.pk).status == "created"
    create2_salt_later = create2_model.objects.get(pk=create2_salt_drop.pk)
    assert create2_salt_later.status == "dropped"
    assert create2_salt_later.failure_reason == ""

    assert create2_model.objects.get(pk=create2_collector_keep.pk).status == "created"
    create2_collector_later = create2_model.objects.get(pk=create2_collector_drop.pk)
    assert create2_collector_later.status == "dropped"
    assert create2_collector_later.failure_reason == ""


@pytest.mark.django_db(transaction=True)
def test_broadcasted_duplicate_group_aborts_migration():
    executor = MigrationExecutor(connection)
    target_before = _targets_with_evm(
        executor,
        "0006_alter_contractdeploycollection_failure_reason_and_more",
    )
    executor.migrate(target_before)
    old_apps = executor.loader.project_state(target_before).apps

    chain = _create_minimal_chain(old_apps, suffix="idem-conflict")
    crypto = _create_minimal_crypto(old_apps, suffix="idem-conflict")
    address = _create_minimal_address(old_apps, suffix="idem-conflict")
    keep = _create_x402(
        old_apps,
        chain=chain,
        crypto=crypto,
        address=address,
        nonce=b"\x31" * 32,
    )
    conflict = _create_x402(
        old_apps,
        chain=chain,
        crypto=crypto,
        address=address,
        nonce=b"\x31" * 32,
        status="broadcasted",
    )

    executor = MigrationExecutor(connection)
    target_after = _targets_with_evm(
        executor,
        "0007_evm_idempotency_constraints",
    )
    try:
        with pytest.raises(RuntimeError) as exc_info:
            executor.migrate(target_after)
    finally:
        old_apps.get_model("evm", "X402Facilitation").objects.filter(
            pk=conflict.pk,
        ).update(status="dropped", failure_reason="")
        executor = MigrationExecutor(connection)
        executor.migrate(target_after)

    message = str(exc_info.value)
    assert str(keep.pk) in message
    assert str(conflict.pk) in message


def _create_x402(
    apps,
    *,
    chain,
    crypto,
    address,
    nonce,
    status="created",
):
    X402Facilitation = apps.get_model("evm", "X402Facilitation")
    return X402Facilitation.objects.create(
        chain=chain,
        crypto=crypto,
        facilitator_address=address,
        authorization_from_address=Web3.to_checksum_address("0x" + "41" * 20),
        authorization_to_address=Web3.to_checksum_address("0x" + "42" * 20),
        authorization_value_raw=1_000_000,
        valid_after=1_700_000_000,
        valid_before=1_700_000_900,
        authorization_nonce=nonce,
        authorization_v=27,
        authorization_r=b"\x43" * 32,
        authorization_s=b"\x44" * 32,
        status=status,
        failure_reason="expected_transfer_missing",
    )


def _create_create2(
    apps,
    *,
    chain,
    crypto,
    address,
    salt,
    collector_suffix,
    status="created",
):
    ContractDeployCollection = apps.get_model("evm", "ContractDeployCollection")
    return ContractDeployCollection.objects.create(
        chain=chain,
        crypto=crypto,
        deployer_address=address,
        factory_address=Web3.to_checksum_address("0x" + "51" * 20),
        collector_address=Web3.to_checksum_address("0x" + collector_suffix * 20),
        vault_address=Web3.to_checksum_address("0x" + "52" * 20),
        salt=salt,
        collector_init_code_hash=b"\x53" * 32,
        expected_collect_value_raw=1_000_000,
        status=status,
        failure_reason="expected_transfer_missing",
    )


def _create_minimal_chain(apps, *, suffix):
    Crypto = apps.get_model("currencies", "Crypto")
    Chain = apps.get_model("chains", "Chain")
    native = Crypto.objects.create(
        name=f"Migration Idempotency Native {suffix}",
        symbol=f"MIN{suffix[:3].upper()}",
        coingecko_id=f"migration-idempotency-native-{suffix}",
    )
    return Chain.objects.create(
        code=f"migration-idempotency-{suffix}",
        chain_id=990_000 + len(suffix),
        name=f"Migration Idempotency {suffix}",
        type="evm",
        native_coin=native,
    )


def _create_minimal_crypto(apps, *, suffix):
    Crypto = apps.get_model("currencies", "Crypto")
    return Crypto.objects.create(
        name=f"Migration Idempotency Token {suffix}",
        symbol=f"MIT{suffix[:3].upper()}",
        coingecko_id=f"migration-idempotency-token-{suffix}",
    )


def _create_minimal_address(apps, *, suffix):
    Wallet = apps.get_model("chains", "Wallet")
    Address = apps.get_model("chains", "Address")
    wallet = Wallet.objects.create()
    return Address.objects.create(
        wallet=wallet,
        chain_type="evm",
        usage="vault",
        bip44_account=0,
        address_index=0,
        address=Web3.to_checksum_address("0x" + f"{len(suffix):040x}"),
    )


def _targets_with_evm(executor, evm_migration):
    graph = executor.loader.graph
    evm_apps_order: dict[str, int] = {
        name: idx
        for idx, (app, name) in enumerate(
            graph.forwards_plan(("evm", graph.leaf_nodes("evm")[0][1])),
        )
        if app == "evm"
    }
    target_evm_index = evm_apps_order[evm_migration]

    def is_compatible(node: tuple[str, str]) -> bool:
        for app, name in graph.forwards_plan(node):
            if app == "evm" and evm_apps_order.get(name, -1) > target_evm_index:
                return False
        return True

    targets: list[tuple[str, str]] = [("evm", evm_migration)]
    apps_with_nodes: dict[str, list[str]] = {}
    for app, name in graph.nodes:
        if app == "evm":
            continue
        apps_with_nodes.setdefault(app, []).append(name)
    for app, names in apps_with_nodes.items():
        for name in sorted(names, reverse=True):
            if is_compatible((app, name)):
                targets.append((app, name))
                break
    return targets
