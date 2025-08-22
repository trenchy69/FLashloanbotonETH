const { expect, assert } = require("chai");
const { ethers } = require("hardhat");
const { impersonateFundErc20 } = require("../utils/utilities");

const {
  abi,
} = require("../artifacts/contracts/interfaces/IERC20.sol/IERC20.json");

const provider = ethers.provider;

describe("FlashSwap Contract", () => {
  let FLASHSWAP, BORROW_AMOUNT, FUND_AMOUNT, initialFundingHuman, txArbitrage;

  const DECIMALS = 18;
  const DECIMALS1 = 6

  const WETH_WHALE = "0xde0B295669a9FD93d5F28D9Ec85E40f4cb697BAe";
  const WETH = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2";
  const USDT = "0xdAC17F958D2ee523a2206206994597C13D831ec7";

  const BASE_TOKEN_ADDRESS = WETH;

  const tokenBase = new ethers.Contract(BASE_TOKEN_ADDRESS, abi, provider);

  before(async () => {
    // Get owner as signer
    [owner] = await ethers.getSigners();

    // Ensure that the WHALE has a balance
    const whale_balance = await provider.getBalance(WETH_WHALE);
    expect(whale_balance).not.equal("0");
    console.log("Whale Balance:", ethers.formatUnits(whale_balance, DECIMALS));

    // Deploy smart contract
    const FlashSwap = await ethers.getContractFactory("UniswapCrossFlash");
    FLASHSWAP = await FlashSwap.deploy();
    await FLASHSWAP.waitForDeployment();
    console.log("Contract Address:", FLASHSWAP.target);

    // Configure our Borrowing
    const borrowAmountHuman = "4";
    BORROW_AMOUNT = ethers.parseUnits(borrowAmountHuman, DECIMALS);

    // Configure Funding - FOR TESTING ONLY
    initialFundingHuman = "10";
    FUND_AMOUNT = ethers.parseUnits(initialFundingHuman, DECIMALS);

    // Fund our Contract - FOR TESTING ONLY
    await impersonateFundErc20(
      tokenBase,
      WETH_WHALE,
      FLASHSWAP.target,
      initialFundingHuman,
      DECIMALS
    );
  });

  describe("Arbitrage Execution", () => {
    it("ensures the contract is funded", async () => {
      const flashSwapBalance = await FLASHSWAP.getBalanceOfToken(
        BASE_TOKEN_ADDRESS
      );

      const flashSwapBalanceHuman = ethers.formatUnits(
        flashSwapBalance,
        DECIMALS
      );

      expect(Number(flashSwapBalanceHuman)).equal(Number(initialFundingHuman));
    });

    it("executes the arbitrage", async () => {
      txArbitrage = await FLASHSWAP.startArbitrage(
        BASE_TOKEN_ADDRESS,
        BORROW_AMOUNT,
        3
      );

      assert(txArbitrage);

      // Print balances
      const contractBalanceWETH = await FLASHSWAP.getBalanceOfToken(WETH);
      const formattedBalWETH = Number(
        ethers.formatUnits(contractBalanceWETH, DECIMALS)
      );

      console.log("Balance of WETH: " + formattedBalWETH);

      const contractBalanceUSDT = await FLASHSWAP.getBalanceOfToken(USDT);
      const formattedBalUSDT = Number(
        ethers.formatUnits(contractBalanceUSDT, DECIMALS1)
      );
      console.log("Balance of USDT: " + formattedBalUSDT);
    });

    it("provides GAS output", async () => {
      const txReceipt = await provider.getTransactionReceipt(txArbitrage.hash);
      const effGasPrice = txReceipt.gasPrice;
      console.log(effGasPrice);
      const txGasUsed = txReceipt.gasUsed;
      console.log(txGasUsed);
      const gasUsedETH = effGasPrice * txGasUsed;
      console.log(
        "Total Gas USD: " +
          ethers.formatEther(gasUsedETH.toString()) * 1800 // exchange rate today
      );
      expect(gasUsedETH).not.equal(0);
    });
  });
});
