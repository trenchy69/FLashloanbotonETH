//SPDX-License-Identifier: Unlicense
pragma solidity >=0.6.6;

import "hardhat/console.sol";

// Uniswap interface and library imports
import "./libraries/UniswapV2Library.sol";
import "./libraries/SafeERC20.sol";
import "./interfaces/IUniswapV2Router01.sol";
import "./interfaces/IUniswapV2Router02.sol";
import "./interfaces/IUniswapV2Pair.sol";
import "./interfaces/IUniswapV2Factory.sol";
import "./interfaces/IERC20.sol";

contract UniswapCrossFlash {
    using SafeERC20 for IERC20;

    // Factory and Routing Addresses
    address private constant UNISWAP_FACTORY =
        0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f;
    address private constant UNISWAP_ROUTER =
        0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D;
    address private constant SUSHI_FACTORY =
        0xC0AEe478e3658e2610c5F7A4A2E1777cE9e4f2Ac;
    address private constant SUSHI_ROUTER =
        0xd9e1cE17f2641f24aE83637ab66a2cca9C378B9F;

    // Token Addresses
    address private constant WETH = 0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2;
    address private constant USDC = 0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48;
    address private constant USDT = 0xdAC17F958D2ee523a2206206994597C13D831ec7;
    address private constant DAI = 0x6B175474E89094C44Da98b954EedeAC495271d0F;

    // Trade Variables
    uint256 private deadline = block.timestamp + 1 days;
    uint256 private constant MAX_INT =
        115792089237316195423570985008687907853269984665640564039457584007913129639935;

    // Access Control
    address public owner;
    
    modifier onlyOwner() {
        require(msg.sender == owner, "Only owner can execute");
        _;
    }

    constructor() {
        owner = msg.sender;
        
        // One-time token approvals
        IERC20(WETH).safeApprove(address(UNISWAP_ROUTER), MAX_INT);
        IERC20(USDC).safeApprove(address(UNISWAP_ROUTER), MAX_INT);
        IERC20(USDT).safeApprove(address(UNISWAP_ROUTER), MAX_INT);
        IERC20(DAI).safeApprove(address(UNISWAP_ROUTER), MAX_INT);

        IERC20(WETH).safeApprove(address(SUSHI_ROUTER), MAX_INT);
        IERC20(USDC).safeApprove(address(SUSHI_ROUTER), MAX_INT);
        IERC20(USDT).safeApprove(address(SUSHI_ROUTER), MAX_INT);
        IERC20(DAI).safeApprove(address(SUSHI_ROUTER), MAX_INT);
    }

    // FUND SMART CONTRACT
    // Provides a function to allow contract to be funded
    function fundFlashSwapContract(
        address owner,
        address token,
        uint256 amount
    ) public {
        IERC20(token).transferFrom(owner, address(this), amount);
    }

    // GET CONTRACT BALANCE
    // Allows public view of balance for contract
    function getBalanceOfToken(address _address) public view returns (uint256) {
        return IERC20(_address).balanceOf(address(this));
    }

    // PLACE A TRADE
    // Executed placing a trade
    function placeTrade(
        address _fromToken,
        address _toToken,
        uint256 _amountIn,
        address factory,
        address router
    ) private returns (uint256) {
        address pair = IUniswapV2Factory(factory).getPair(_fromToken, _toToken);
        require(pair != address(0), "Pool does not exist");

        // Calculate Amount Out
        address[] memory path = new address[](2);
        path[0] = _fromToken;
        path[1] = _toToken;

        uint256 amountRequired = IUniswapV2Router01(router).getAmountsOut(
            _amountIn,
            path
        )[1];

        // Perform Arbitrage - Swap for another token
        uint256 amountReceived = IUniswapV2Router01(router)
            .swapExactTokensForTokens(
                _amountIn, // amountIn
                amountRequired, // amountOutMin
                path, // path
                address(this), // address to
                deadline // deadline
            )[1];

        require(amountReceived > 0, "Aborted Tx: Trade returned zero");

        return amountReceived;
    }

    // CHECK PROFITABILITY
    // Checks whether > output > input
    function checkProfitability(uint256 _input, uint256 _output)
        pure
        private
        returns (bool)
    {
        return _output > _input;
    }

    // INITIATE ARBITRAGE
    // Begins receiving loan to engage performing arbitrage trades
    function startArbitrage(address _tokenBorrow, uint256 _amount , uint8 pathflag) external onlyOwner {
        // Get the Factory Pair address for combined tokens
        address pair = IUniswapV2Factory(UNISWAP_FACTORY).getPair(
            _tokenBorrow,
            USDC
        );
        // Return error if combination does not exist
        require(pair != address(0), "Pool does not exist");

        // Figure out which token (0 or 1) has the amount and assign
        address token0 = IUniswapV2Pair(pair).token0();
        address token1 = IUniswapV2Pair(pair).token1();
        uint256 amount0Out = _tokenBorrow == token0 ? _amount : 0;
        uint256 amount1Out = _tokenBorrow == token1 ? _amount : 0;

        // Passing data as bytes so that the 'swap' function knows it is a flashloan
        bytes memory data = abi.encode(_tokenBorrow, _amount, msg.sender, pathflag);

        // Execute the initial swap to get the loan
        IUniswapV2Pair(pair).swap(amount0Out, amount1Out, address(this), data);
    }

    function uniswapV2Call(
        address sender,
        uint256 amount0,
        uint256 amount1,
        bytes calldata data
    ) external {
        // Ensure this request came from the contract
        address token0 = IUniswapV2Pair(msg.sender).token0();
        address token1 = IUniswapV2Pair(msg.sender).token1();
        address pair = IUniswapV2Factory(UNISWAP_FACTORY).getPair(
            token0,
            token1
        );
        require(msg.sender == pair, "The sender needs to match the pair");
        require(sender == address(this), "Sender should match this contract");

        // Decode data for calculating the repayment
        (address tokenBorrow, uint256 amount, address myAddress, uint8 pathflag) = abi.decode(
            data,
            (address, uint256, address, uint8)
        );

        // Calculate the amount to repay at the end
        uint256 fee = ((amount * 3 )/ 997) +1 ;
        uint256 amountToRepay = amount + fee;

        // DO ARBITRAGE

        // Assign loan amount
        require(amount0 > 0 ? token0 == tokenBorrow : token1 == tokenBorrow, "Incorrect loan token");
        uint256 loanAmount = amount0 > 0 ? amount0 : amount1;

        uint256 finalWETH;

        if (pathflag == 0){
            uint256 trade1AcquiredDAI = placeTrade(
                WETH,
                DAI,
                loanAmount,
                UNISWAP_FACTORY,
                UNISWAP_ROUTER
        );
            finalWETH = placeTrade(
                DAI,
                WETH,
                trade1AcquiredDAI,
                SUSHI_FACTORY,
                SUSHI_ROUTER
        );} else if (pathflag == 1 ){
            uint256 trade2AcquiredDAI = placeTrade(
                WETH,
                DAI,
                loanAmount,
                SUSHI_FACTORY,
                SUSHI_ROUTER
        );
            finalWETH = placeTrade(
                DAI,
                WETH,
                trade2AcquiredDAI,
                UNISWAP_FACTORY,
                UNISWAP_ROUTER
         );} else if (pathflag == 2 ){
            uint256 trade1AcquiredUSDT = placeTrade(
                WETH,
                USDT,
                loanAmount,
                UNISWAP_FACTORY,
                UNISWAP_ROUTER
        );
            finalWETH = placeTrade(
                USDT,
                WETH,
                trade1AcquiredUSDT,
                SUSHI_FACTORY,
                SUSHI_ROUTER
        );} else if (pathflag == 3 ){
            uint256 trade2AcquiredUSDT = placeTrade(
                WETH,
                USDT,
                loanAmount,
                SUSHI_FACTORY,
                SUSHI_ROUTER
        );
            // FIX: Complete the second trade back to WETH
            finalWETH = placeTrade(
                USDT,
                WETH,
                trade2AcquiredUSDT,
                UNISWAP_FACTORY,
                UNISWAP_ROUTER
            );
        }

        // Check Profitability
        bool profCheck = checkProfitability(amountToRepay, finalWETH);
        require(profCheck, "Arbitrage not profitable");

        // Pay Myself
        IERC20 otherToken = IERC20(WETH);
        otherToken.transfer(myAddress, finalWETH - amountToRepay);

        // Pay Loan Back
        IERC20(tokenBorrow).transfer(pair, amountToRepay);
    }

    // Emergency function to withdraw tokens
    function emergencyWithdraw(address token) external onlyOwner {
        uint256 balance = IERC20(token).balanceOf(address(this));
        IERC20(token).transfer(owner, balance);
    }
}
