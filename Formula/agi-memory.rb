class AgiMemory < Formula
  include Language::Python::Virtualenv

  desc "Turnkey zero-dependency four-pillar cognitive memory framework for AI coding assistants"
  homepage "https://github.com/kdbhalala/agi-memory"
  url "https://github.com/kdbhalala/agi-memory/archive/refs/tags/v0.10.1.tar.gz"
  sha256 "0c8520caaba7d897be2e69902f4022c26c8876f93350073658c9a94ff6f96a1c"
  license "MIT"
  head "https://github.com/kdbhalala/agi-memory.git", branch: "main"

  depends_on "python@3.13"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "agi-memory 0.10.1", shell_output("#{bin}/agi-memory --version")
    assert_match "Turnkey integration tool", shell_output("#{bin}/agi-integrate --help")
    assert_match "Recall from agent session", shell_output("#{bin}/agi-recall --help")
  end
end
