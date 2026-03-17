"""
ContentBank CLI commands.
Usage: contentbank <command>

Commands:
  keygen    Generate a new node key pair and print to stdout
  serve     Start the API server (alias for contentbank.main:main)
"""

import sys


def keygen():
    """Generate a P-256 key pair for this node."""
    from contentbank.auth.keys import generate_key_pair, private_key_to_pem

    private_key, public_key_b64 = generate_key_pair()
    pem = private_key_to_pem(private_key)

    print("# Add these to your .env file (or set as environment variables):\n")
    print(f'CB_NODE_PUBLIC_KEY="{public_key_b64}"')
    print(f'CB_NODE_PRIVATE_KEY="{pem.strip()}"')
    print("\n# Keep CB_NODE_PRIVATE_KEY secret. Never commit it to version control.")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]
    if command == "keygen":
        keygen()
    elif command == "serve":
        from contentbank.main import main as serve
        serve()
    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
