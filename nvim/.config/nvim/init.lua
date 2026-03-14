local lazypath = vim.fn.stdpath("data") .. "/lazy/lazy.nvim"

if not vim.loop.fs_stat(lazypath) then
  vim.fn.system({
    "git",
    "clone",
    "--filter=blob:none",
    "https://github.com/folke/lazy.nvim.git",
    "--branch=stable",
    lazypath,
  })
end

vim.opt.rtp:prepend(lazypath)

require("lazy").setup({
  { "catppuccin/nvim", name = "catppuccin", priority = 1000 },

  { "nvim-tree/nvim-tree.lua" },

  { "nvim-treesitter/nvim-treesitter", build = ":TSUpdate" },

  { "nvim-lua/plenary.nvim" },

  { "nvim-telescope/telescope.nvim" },
})

require("catppuccin").setup({
  flavour = "mocha",
  transparent_background = false,
  integrations = {
    cmp = true,
    gitsigns = true,
    treesitter = true,
    telescope = true,
    native_lsp = {
      enabled = true,
    },
  },
  highlight_overrides = {
    mocha = function(colors)
      return {
        CursorLineNr = { fg = "#94e2d5", style = { "bold" } },
        Search = { bg = "#94e2d5", fg = "#1e1e2e" },
        IncSearch = { bg = "#94e2d5", fg = "#1e1e2e" },
        Visual = { bg = "#45475a" },
        PmenuSel = { bg = "#94e2d5", fg = "#1e1e2e" },
        TelescopeSelection = { bg = "#313244", fg = "#94e2d5" },
        TelescopeMatching = { fg = "#94e2d5", style = { "bold" } },
      }
    end,
  },
})

vim.cmd.colorscheme("catppuccin")

vim.opt.number = true
vim.opt.relativenumber = true
vim.opt.termguicolors = true
vim.opt.expandtab = true
vim.opt.shiftwidth = 2
vim.opt.tabstop = 2
vim.opt.smartindent = true
vim.opt.mouse = "a"
vim.opt.scrolloff = 8
