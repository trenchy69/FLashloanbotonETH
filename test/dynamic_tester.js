const { expect, assert } = require("chai");
const { ethers } = require("hardhat");
const { impersonateFundErc20 } = require("../utils/utilities");

const {
  abi,
} = require("../artifacts/contracts/interfaces/IERC20.sol/IERC20.json");

const provider = ethers.provider;

describe("FlashSwap Contract - Dynamic Path Testing", () => {
  let FLASHSWAP, BORROW_AMOUNT, FUND_AMOUNT, initialFundingHuman;

  const DECIMALS = 18;
  const DECIMALS_USDC = 6;
  const DECIMALS_USDT = 6;

  const WETH_WHALE = "0xde0B295669a9FD93d5F28D9Ec85E40f4cb697BAe";
  const WETH = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2";
  const USDC = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48";
  const USDT = "0xdAC17F958D2ee523a2206206994597C13D831ec7";
  const DAI = "0x6B175474E89094C44Da98b954EedeAC495271d0F";

  const BASE_TOKEN_ADDRESS = WETH;

  // Path descriptions for better logging
  const pathDescriptions = {
    0: "WETH → DAI (Uniswap) → WETH (Sushiswap)",
    1: "WETH → DAI (Sushiswap) → WETH (Uniswap)", 
    2: "WETH → USDT (Uniswap) → WETH (Sushiswap)",
    3: "WETH → USDT (Sushiswap) → WETH (Uniswap)"
  };

  const tokenBase = new ethers.Contract(BASE_TOKEN_ADDRESS, abi, provider);

  let testResults = {
    profitable: [],
    unprofitable: [],
    failed: []
  };

  before(async () => {
    console.log("\n🚀 Starting Dynamic Arbitrage Path Testing...\n");

    // Get owner as signer
    [owner] = await ethers.getSigners();

    // Ensure that the WHALE has a balance
    const whale_balance = await provider.getBalance(WETH_WHALE);
    expect(whale_balance).not.equal("0");
    console.log("💰 Whale Balance:", ethers.formatUnits(whale_balance, DECIMALS));

    // Deploy smart contract
    const FlashSwap = await ethers.getContractFactory("UniswapCrossFlash");
    FLASHSWAP = await FlashSwap.deploy();
    await FLASHSWAP.waitForDeployment();
    console.log("📋 Contract Address:", FLASHSWAP.target);

    // Configure our Borrowing
    const borrowAmountHuman = "3";
    BORROW_AMOUNT = ethers.parseUnits(borrowAmountHuman, DECIMALS);

    // Configure Funding - FOR TESTING ONLY
    initialFundingHuman = "5"; // Slightly more funding for safety
    FUND_AMOUNT = ethers.parseUnits(initialFundingHuman, DECIMALS);

    // Fund our Contract - FOR TESTING ONLY
    await impersonateFundErc20(
      tokenBase,
      WETH_WHALE,
      FLASHSWAP.target,
      initialFundingHuman,
      DECIMALS
    );

    console.log(`💵 Contract funded with ${initialFundingHuman} WETH\n`);
  });

  describe("Contract Setup", () => {
    it("ensures the contract is funded", async () => {
      const flashSwapBalance = await FLASHSWAP.getBalanceOfToken(BASE_TOKEN_ADDRESS);
      const flashSwapBalanceHuman = ethers.formatUnits(flashSwapBalance, DECIMALS);
      expect(Number(flashSwapBalanceHuman)).equal(Number(initialFundingHuman));
      console.log("✅ Contract successfully funded");
    });
  });

  describe("Dynamic Path Testing", () => {
    // Test all 4 paths dynamically
    for (let pathIndex = 0; pathIndex < 4; pathIndex++) {
      it(`tests path ${pathIndex}: ${pathDescriptions[pathIndex]}`, async () => {
        console.log(`\n🧪 Testing Path ${pathIndex}: ${pathDescriptions[pathIndex]}`);
        
        // Record initial balances
        const initialWETH = await FLASHSWAP.getBalanceOfToken(WETH);
        const initialUSDC = await FLASHSWAP.getBalanceOfToken(USDC);
        const initialUSDT = await FLASHSWAP.getBalanceOfToken(USDT);
        const initialDAI = await FLASHSWAP.getBalanceOfToken(DAI);

        try {
          // Attempt arbitrage
          const txArbitrage = await FLASHSWAP.startArbitrage(
            BASE_TOKEN_ADDRESS,
            BORROW_AMOUNT,
            pathIndex
          );

          // If we reach here, the transaction succeeded
          assert(txArbitrage);
          console.log("✅ Path", pathIndex, "- PROFITABLE! 🎉");

          // Calculate gas costs
          const txReceipt = await provider.getTransactionReceipt(txArbitrage.hash);
          const gasUsed = txReceipt.gasUsed;
          const gasPrice = txReceipt.gasPrice;
          const gasCostETH = gasUsed * gasPrice;
          const gasCostUSD = Number(ethers.formatEther(gasCostETH)) * 1800; // Approximate ETH price

          // Record final balances
          const finalWETH = await FLASHSWAP.getBalanceOfToken(WETH);
          const finalUSDC = await FLASHSWAP.getBalanceOfToken(USDC);
          const finalUSDT = await FLASHSWAP.getBalanceOfToken(USDT);
          const finalDAI = await FLASHSWAP.getBalanceOfToken(DAI);

          // Calculate profit
          const wethProfit = finalWETH - initialWETH;
          const profitETH = Number(ethers.formatEther(wethProfit));

          console.log("💰 WETH Profit:", profitETH.toFixed(6), "ETH");
          console.log("⛽ Gas Cost: $" + gasCostUSD.toFixed(2));
          console.log("📊 Net Profit: $" + (profitETH * 1800 - gasCostUSD).toFixed(2));

          // Add to profitable paths
          testResults.profitable.push({
            path: pathIndex,
            description: pathDescriptions[pathIndex],
            profitETH: profitETH,
            gasCostUSD: gasCostUSD,
            netProfitUSD: (profitETH * 1800 - gasCostUSD),
            txHash: txArbitrage.hash
          });

        } catch (error) {
          if (error.message.includes("Arbitrage not profitable")) {
            console.log("❌ Path", pathIndex, "- Not profitable at current prices");
            testResults.unprofitable.push({
              path: pathIndex,
              description: pathDescriptions[pathIndex],
              reason: "Not profitable"
            });
            // This is expected behavior, not a test failure
            expect(error.message).to.include("Arbitrage not profitable");
          } else {
            console.log("💥 Path", pathIndex, "- Failed with error:", error.message);
            testResults.failed.push({
              path: pathIndex,
              description: pathDescriptions[pathIndex],
              error: error.message
            });
            throw error; // Re-throw unexpected errors
          }
        }
      });
    }
  });

  describe("Test Summary", () => {
    it("provides comprehensive results summary", async () => {
      console.log("\n" + "=".repeat(60));
      console.log("📊 ARBITRAGE PATHS TEST SUMMARY");
      console.log("=".repeat(60));

      if (testResults.profitable.length > 0) {
        console.log("\n✅ PROFITABLE PATHS:");
        testResults.profitable.forEach(result => {
          console.log(`   Path ${result.path}: ${result.description}`);
          console.log(`   💰 Profit: ${result.profitETH.toFixed(6)} ETH ($${(result.profitETH * 1800).toFixed(2)})`);
          console.log(`   ⛽ Gas Cost: $${result.gasCostUSD.toFixed(2)}`);
          console.log(`   📈 Net Profit: $${result.netProfitUSD.toFixed(2)}`);
          console.log(`   🔗 Tx Hash: ${result.txHash}\n`);
        });
      }

      if (testResults.unprofitable.length > 0) {
        console.log("\n❌ UNPROFITABLE PATHS:");
        testResults.unprofitable.forEach(result => {
          console.log(`   Path ${result.path}: ${result.description} - ${result.reason}`);
        });
      }

      if (testResults.failed.length > 0) {
        console.log("\n💥 FAILED PATHS:");
        testResults.failed.forEach(result => {
          console.log(`   Path ${result.path}: ${result.description} - ${result.error}`);
        });
      }

      console.log("\n" + "=".repeat(60));
      console.log(`📈 Total Profitable: ${testResults.profitable.length}/4`);
      console.log(`❌ Total Unprofitable: ${testResults.unprofitable.length}/4`);
      console.log(`💥 Total Failed: ${testResults.failed.length}/4`);
      console.log("=".repeat(60));

      // Recommendations
      if (testResults.profitable.length > 0) {
        const bestPath = testResults.profitable.reduce((best, current) => 
          current.netProfitUSD > best.netProfitUSD ? current : best
        );
        console.log(`\n🏆 BEST PATH: Path ${bestPath.path} with $${bestPath.netProfitUSD.toFixed(2)} net profit`);
      } else {
        console.log("\n💡 RECOMMENDATION: No profitable paths found at current market prices.");
        console.log("   Try again later when market conditions change or consider:");
        console.log("   - Different trade amounts");
        console.log("   - Additional DEX pairs"); 
        console.log("   - Lower gas price periods");
      }

      console.log("\n");

      // Test should pass regardless - we're testing system functionality
      expect(testResults.profitable.length + testResults.unprofitable.length + testResults.failed.length).to.equal(4);
    });
  });
});