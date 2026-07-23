"""Platform name normalization shared by packaging and the updater."""


def normalize_system(system: str) -> str:
    system = system.lower()
    if system == "darwin":
        return "macos"
    if system == "windows":
        return "windows"
    return "linux"


def normalize_arch(machine: str) -> str:
    machine = machine.lower()
    if machine in {"x86_64", "amd64"}:
        return "amd64"
    if machine in {"aarch64", "arm64"} or machine.startswith("arm"):
        return "arm64"
    return machine
