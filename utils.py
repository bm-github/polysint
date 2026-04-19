from web3 import Web3
from config import Config
from logger import get_logger

log = get_logger("Blockchain")

w3 = Web3(Web3.HTTPProvider(Config.RPC_URL))

GNOSIS_SAFE_ABI_FRAGMENT = [
    {
        "inputs": [],
        "name": "getOwners",
        "outputs": [{"internalType": "address[]", "name": "", "type": "address[]"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "getThreshold",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "getModules",
        "outputs": [{"internalType": "address[]", "name": "", "type": "address[]"}],
        "stateMutability": "view",
        "type": "function",
    },
]

MAX_RECURSION_DEPTH = 5


def _is_contract(address: str) -> bool:
    try:
        code = w3.eth.get_code(w3.to_checksum_address(address))
        return code and code != b'' and code != b'\x00'
    except Exception:
        return False


def _safe_get_owners(address: str) -> list[str]:
    try:
        contract = w3.eth.contract(
            address=w3.to_checksum_address(address),
            abi=GNOSIS_SAFE_ABI_FRAGMENT,
        )
        owners = contract.functions.getOwners().call()
        return [w3.to_checksum_address(o) for o in owners]
    except Exception:
        try:
            response = w3.eth.call({
                'to': w3.to_checksum_address(address),
                'data': '0xa0e67e2b',
            })
            if not response or len(response) < 32:
                return []
            return [w3.to_checksum_address("0x" + response.hex()[-40:])]
        except Exception:
            return []


def _safe_get_threshold(address: str) -> int | None:
    try:
        contract = w3.eth.contract(
            address=w3.to_checksum_address(address),
            abi=GNOSIS_SAFE_ABI_FRAGMENT,
        )
        return contract.functions.getThreshold().call()
    except Exception:
        try:
            response = w3.eth.call({
                'to': w3.to_checksum_address(address),
                'data': '0xe75235b8',
            })
            if response and len(response) >= 32:
                return int.from_bytes(response[:32], 'big')
        except Exception:
            pass
    return None


def _safe_get_modules(address: str) -> list[str]:
    try:
        contract = w3.eth.contract(
            address=w3.to_checksum_address(address),
            abi=GNOSIS_SAFE_ABI_FRAGMENT,
        )
        modules = contract.functions.getModules().call()
        return [w3.to_checksum_address(m) for m in modules]
    except Exception:
        return []


def _recursive_unmask(address: str, depth: int = 0, visited: set | None = None) -> dict:
    if visited is None:
        visited = set()

    address = w3.to_checksum_address(address)

    if address in visited or depth > MAX_RECURSION_DEPTH:
        return {
            "address": address,
            "type": "MAX_DEPTH_OR_CYCLE",
            "owner": address,
            "threshold": None,
            "modules": [],
            "owner_chain": [],
        }

    visited.add(address)

    if not _is_contract(address):
        return {
            "address": address,
            "type": "EOA",
            "owner": address,
            "threshold": None,
            "modules": [],
            "owner_chain": [address],
        }

    owners = _safe_get_owners(address)
    threshold = _safe_get_threshold(address)
    modules = _safe_get_modules(address)

    if not owners:
        return {
            "address": address,
            "type": "CONTRACT_UNKNOWN",
            "owner": address,
            "threshold": threshold,
            "modules": modules,
            "owner_chain": [address],
        }

    primary_owner = owners[0]
    owner_chain = [address]

    if _is_contract(primary_owner):
        nested = _recursive_unmask(primary_owner, depth + 1, visited)
        owner_chain.extend(nested.get("owner_chain", [primary_owner]))
        final_owner = nested["owner"]
    else:
        owner_chain.append(primary_owner)
        final_owner = primary_owner

    sig_type = "MULTI-SIG" if (threshold and threshold > 1) else "SINGLE-SIG"

    return {
        "address": address,
        "type": f"GNOSIS_SAFE({sig_type})",
        "owner": final_owner,
        "threshold": threshold,
        "modules": modules,
        "all_owners": owners,
        "owner_chain": owner_chain,
    }


def unmask_proxy(proxy_address: str) -> str:
    try:
        result = _recursive_unmask(proxy_address)
        return result["owner"]
    except Exception as e:
        log.info(f"Unmask check for {proxy_address} failed: {e}")
        return "Direct Wallet (Not a Proxy)"


def unmask_proxy_full(proxy_address: str) -> dict:
    try:
        return _recursive_unmask(proxy_address)
    except Exception as e:
        log.info(f"Full unmask check for {proxy_address} failed: {e}")
        return {
            "address": proxy_address,
            "type": "ERROR",
            "owner": "Unknown",
            "threshold": None,
            "modules": [],
            "owner_chain": [],
            "error": str(e),
        }
