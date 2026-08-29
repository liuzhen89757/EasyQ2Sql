"""
Interactive example runner for EasyQ2Sql.
"""

import sys
import importlib


def main() -> None:
    """Run an example interactively."""
    if len(sys.argv) < 2:
        print("Available examples:")
        print("  python -m easyq2sql.examples mock_quickstart")
        print("  python -m easyq2sql.examples mock_custom_tool")
        print("  python -m easyq2sql.examples anthropic_quickstart")
        print("  python -m easyq2sql.examples openai_quickstart")
        print("  python -m easyq2sql.examples mock_quota_example")
        print("  python -m easyq2sql.examples mock_rich_components_demo")
        print("")
        print("Usage: python -m easyq2sql.examples <example_name>")
        return

    example_name = sys.argv[1]
    try:
        module = importlib.import_module(f"easyq2sql.examples.{example_name}")
        if hasattr(module, "run_interactive"):
            module.run_interactive()
        elif hasattr(module, "main"):
            import asyncio

            if asyncio.iscoroutinefunction(module.main):
                asyncio.run(module.main())
            else:
                module.main()
        else:
            print(f"Example '{example_name}' does not have a main function")
    except ImportError:
        print(f"Example '{example_name}' not found")
    except Exception as e:
        print(f"Error running example '{example_name}': {e}")


if __name__ == "__main__":
    main()
