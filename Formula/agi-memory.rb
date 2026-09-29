class AgiMemory < Formula
  include Language::Python::Virtualenv

  desc "Turnkey zero-dependency four-pillar cognitive memory framework for AI coding assistants"
  homepage "https://github.com/kdbhalala/agi-memory"
  url "https://github.com/kdbhalala/agi-memory/archive/refs/tags/v0.10.0.tar.gz"
  sha256 "109680a8d699fcf035486cc007cf903367ea94698e6a6e8cde6cfdca34948395"
  license "MIT"
  head "https://github.com/kdbhalala/agi-memory.git", branch: "main"

  depends_on "python@3.13"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "agi-memory 0.10.0", shell_output("#{bin}/agi-memory --version")
    assert_match "Turnkey integration tool", shell_output("#{bin}/agi-integrate --help")
    assert_match "Recall from agent session", shell_output("#{bin}/agi-recall --help")
  end
end
