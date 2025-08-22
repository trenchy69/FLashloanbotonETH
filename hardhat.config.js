require("@nomicfoundation/hardhat-toolbox");

/** @type import('hardhat/config').HardhatUserConfig */
module.exports = {
  compilers:[
    {version:"0.5.0"},{version: "0.5.5"},{version:"0.6.0"},{version:"0.6.6"},{version:"0.8.0"},{version:"0.8.28"},
  ],
networks: {
  hardhat:{
    forking:{
    url:"https://eth-mainnet.g.alchemy.com/v2/lNa0QhGRjIvJGFqENQ_w_1eHXqdOCpxr",
    },
  },
  testnet:{
    url:"https://eth-sepolia.g.alchemy.com/v2/lNa0QhGRjIvJGFqENQ_w_1eHXqdOCpxr",
    chainId: 11155111,
    account:["0xd7a5e1e84bd2ca3ed73913c8dc6038474d45c0972121b020792f4ec2d047b2f1"], 
  },
  mainnet:{
    url:"https://eth-mainnet.g.alchemy.com/v2/lNa0QhGRjIvJGFqENQ_w_1eHXqdOCpxr",
    chainId:1,
  },
},
};
