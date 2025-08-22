const { network, ethers } = require("hardhat");

const fundErc20 = async (contract, sender, recepient, amount, decimals) => {
  const FUND_AMOUNT = ethers.parseUnits(amount, decimals);
  // fund erc20 token to the contract
  const whale = await ethers.getSigner(sender);

  const contractSigner = contract.connect(whale);
  await contractSigner.transfer(recepient, FUND_AMOUNT);
};

async function impersonateFundErc20(token, whale, recipient, amount, decimals) {
  // Impersonate the whale account
  await hre.network.provider.request({
    method: "hardhat_impersonateAccount",
    params: [whale],
  });

  const signer = await ethers.getSigner(whale);

  // Transfer tokens to the recipient
  const amountInWei = ethers.parseUnits(amount, decimals);
  await token.connect(signer).transfer(recipient, amountInWei);

  // Stop impersonating the whale account
  await hre.network.provider.request({
    method: "hardhat_stopImpersonatingAccount",
    params: [whale],
  });
}

module.exports = {
  impersonateFundErc20: impersonateFundErc20,
};
