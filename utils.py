from web3 import Web3
from config import Config
from logger import get_logger
log = get_logger("Blockchain")

w3 = Web3(Web3.HTTPProvider(Config.RPC_URL))

def unmask_proxy(proxy_address):
    """Bypasses Polygonscan to find the real EOA owner of a Polymarket wallet."""
    try:
        response = w3.eth.call({
            'to': w3.to_checksum_address(proxy_address),
            'data': '0x7065c0d4' # getOwners() signature
        })
        
        # If the response is empty, it's not a contract
        if not response or response == b'':
            return "Direct Wallet (Not a Proxy)"
            
        owner = w3.to_checksum_address("0x" + response.hex()[-40:])
        return owner
    except Exception as e:
        # A revert error usually means the address is an EOA (Direct Wallet)
        log.info(f"Unmask check for {proxy_address} failed (likely an EOA): {e}")
        return "Direct Wallet (Not a Proxy)"