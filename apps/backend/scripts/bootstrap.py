from services.startup_admin import ensure_platform_admin


def main() -> None:
    admin = ensure_platform_admin()
    if admin is None:
        print("Automatic platform administrator bootstrap is disabled.")
        return
    print(f"Platform administrator ready: {admin.email}")


if __name__ == "__main__":
    main()
