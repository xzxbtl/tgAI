from pathlib import Path
from dotenv import load_dotenv

SCRIPTS_DIR = Path(__file__).resolve().parent.parent


def load_env(*filenames):
    for filename in filenames:
        env_path = SCRIPTS_DIR / "envs" / filename

        if not env_path.is_file():
            raise FileNotFoundError(f"Env file not found: {env_path}")

        load_dotenv(env_path, override=True)


def take_all_envs():
    envs_path = SCRIPTS_DIR / "envs"

    if not envs_path.exists():
        raise FileNotFoundError(f"Envs directory not found: {envs_path}")

    return sorted(envs_path.glob("*.env"))