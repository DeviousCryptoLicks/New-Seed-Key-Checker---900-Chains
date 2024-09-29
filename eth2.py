import json
import asyncio
import aiohttp
from eth_account import Account

# Enable mnemonic-based features in eth_account
Account.enable_unaudited_hdwallet_features()

# Load mnemonics from seeds.txt
def load_mnemonics(file_path):
    with open(file_path, 'r') as file:
        mnemonics = [line.strip() for line in file.readlines()]
    return mnemonics

# Convert mnemonic to Ethereum address using eth_account library
def mnemonic_to_eth_address(mnemonic):
    # Generate account from mnemonic phrase
    acct = Account.from_mnemonic(mnemonic)
    return acct.address

# Load RPC endpoints from chain.json, excluding testnet chains
def load_chain_data(chain_file):
    with open(chain_file, 'r') as file:
        chain_data = json.load(file)
    # Filter out testnet chains
    return [chain for chain in chain_data if not chain.get('isTestnet', False)]

# Log output to a file
def log_output(file_path, message):
    with open(file_path, 'a') as file:
        file.write(message + '\n')

# Save results based on balance (formatted to 18 decimal places)
def save_results(address, mnemonic, balance, chain_name, currency_symbol):
    output = f"Mnemonic: {mnemonic}\nAddress: {address}\nChain: {chain_name} ({currency_symbol})\nBalance: {balance:.18f} {currency_symbol}\n"

    # Log all results in results.txt
    log_output('results.txt', output)

    # Classify balances into low, medium, or high
    if balance < 0.1:
        log_output('low.txt', output)
    elif 0.1 <= balance < 1:
        log_output('medium.txt', output)
    else:
        log_output('high.txt', output)

# Asynchronous function to fetch balance from a given RPC
async def fetch_balance(session, rpc, address):
    try:
        async with session.post(rpc, json={
            "jsonrpc": "2.0",
            "method": "eth_getBalance",
            "params": [address, "latest"],
            "id": 1
        }, timeout=10) as response:
            if response.headers.get('Content-Type') == 'application/json':
                response_data = await response.json()
                balance = int(response_data['result'], 16)
                return balance
            else:
                return None
    except asyncio.TimeoutError:
        return None
    except Exception as e:
        return None

# Asynchronous function to check balance for a given address using the first available RPC
async def check_balance(session, address, network):
    # Get all RPCs for the current network
    rpcs = network.get('RPC', '').split(', ')
    if not rpcs:
        return [None]  # Skip if no RPC available
    # Check the first RPC available
    return [await fetch_balance(session, rpcs[0], address)]  # Just use the first one

# Asynchronous function to check balance across chains with concurrency limit (4 chains at a time)
async def check_chain_with_limit(session, semaphore, eth_address, network):
    chain_name = network.get('Chain', 'Unknown')
    currency_symbol = network.get('Native Currency Symbol', 'ETH')  # Default to 'ETH' if not provided

    async with semaphore:  # Limiting to 4 concurrent checks
        print(f"Checking address on {chain_name} ({currency_symbol})...")
        balances = await check_balance(session, eth_address, network)

        for balance in balances:
            if balance is not None:
                eth_balance = balance / (10 ** int(network['Native Currency Decimals']))
                eth_balance_18_decimals = round(eth_balance, 18)  # Ensure balance is to 18 decimal places
                if eth_balance_18_decimals > 0:
                    print(f"Found balance: {eth_balance_18_decimals:.18f} {currency_symbol} on {chain_name}")
                    return eth_balance_18_decimals, chain_name, currency_symbol

    return None, chain_name, currency_symbol

async def main():
    # File paths
    seeds_file = 'seeds.txt'
    chain_file = 'chain.json'

    # Load mnemonics and chain data
    print("Loading mnemonics from seeds.txt...")
    mnemonics = load_mnemonics(seeds_file)
    print(f"Loaded {len(mnemonics)} mnemonics.")

    print("Loading chain data from chain.json, excluding testnets...")
    chain_data = load_chain_data(chain_file)

    # Use a set to track currencies already checked
    checked_currencies = set()

    async with aiohttp.ClientSession() as session:
        for mnemonic in mnemonics:
            print("\n----------------------------------------")
            print(f"Processing mnemonic: {mnemonic}")
            eth_address = mnemonic_to_eth_address(mnemonic)
            print(f"Derived Ethereum address: {eth_address}")

            # Semaphore to limit concurrency to 4 chains at a time
            semaphore = asyncio.Semaphore(4)

            chains_checked = 0
            balances_found = 0
            unique_balances = set()

            # First check the first 50 chains
            for i, network in enumerate(chain_data[:50]):
                currency_symbol = network.get('Native Currency Symbol', 'ETH')
                # Check if this currency has already been checked
                if currency_symbol in checked_currencies:
                    continue  # Skip checking this currency again

                print(f"Checking address on {network.get('Chain', 'Unknown')} ({currency_symbol})...")
                chains_checked += 1

                # Check balance with semaphore to limit to 4 concurrent checks
                eth_balance, chain_name, currency_symbol = await check_chain_with_limit(session, semaphore, eth_address, network)

                if eth_balance:
                    if eth_balance not in unique_balances:
                        unique_balances.add(eth_balance)
                        balances_found += 1
                        save_results(eth_address, mnemonic, eth_balance, chain_name, currency_symbol)
                        checked_currencies.add(currency_symbol)  # Mark this currency as checked

            # If at least 5 balances found in the first 50, continue checking up to 200
            if balances_found >= 5:
                print(f"Found {balances_found} unique balances in the first 50 chains. Continuing to check up to 200 chains...")
                
                # Continue checking the remaining chains up to 200 total checked
                for network in chain_data[50:200]:
                    currency_symbol = network.get('Native Currency Symbol', 'ETH')
                    # Check if this currency has already been checked
                    if currency_symbol in checked_currencies:
                        continue  # Skip checking this currency again

                    print(f"Checking address on {network.get('Chain', 'Unknown')} ({currency_symbol})...")
                    chains_checked += 1

                    # Check balance with semaphore to limit to 4 concurrent checks
                    eth_balance, chain_name, currency_symbol = await check_chain_with_limit(session, semaphore, eth_address, network)

                    if eth_balance:
                        if eth_balance not in unique_balances:
                            unique_balances.add(eth_balance)
                            balances_found += 1
                            save_results(eth_address, mnemonic, eth_balance, chain_name, currency_symbol)
                            checked_currencies.add(currency_symbol)  # Mark this currency as checked

            print(f"Checked {chains_checked} chains for mnemonic: {mnemonic}. Found {balances_found} unique balances.")
            if balances_found == 0:
                print(f"No positive balance found for mnemonic: {mnemonic}. Moving on to the next mnemonic.")

if __name__ == '__main__':
    asyncio.run(main())
