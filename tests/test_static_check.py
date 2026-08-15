from scripts import static_check


def test_public_package_does_not_require_local_generated_inventory() -> None:
    local_only = {
        "docs/WORKFLOW_USAGE_INVENTORY.json",
        "docs/CUSTOM_NODE_RUNTIME_PATHS.md",
    }

    assert local_only.isdisjoint(static_check.REQUIRED)
