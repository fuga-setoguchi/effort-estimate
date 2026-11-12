"""output_path.py のテスト（標準ライブラリのみ）。

    python3 -m unittest discover tests
"""
import datetime
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = (Path(__file__).resolve().parent.parent
          / "skills" / "effort-estimate" / "scripts" / "output_path.py")
ENV_VAR = "EFFORT_ESTIMATE_OUTPUT_DIR"
HAS_GIT = shutil.which("git") is not None


class OutputPathTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        # macOS では /var が /private/var へのリンクなので、解決しておく
        self.tmp = Path(self._tmp.name).resolve()
        self.today = datetime.date.today().strftime("%Y%m%d")

    def tearDown(self):
        self._tmp.cleanup()

    def run_script(self, *args, cwd=None, env_dir=None):
        env = {k: v for k, v in os.environ.items() if k != ENV_VAR}
        # 親フォルダの Git リポジトリを拾わないようにする
        env["GIT_CEILING_DIRECTORIES"] = str(self.tmp)
        if env_dir is not None:
            env[ENV_VAR] = str(env_dir)
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            capture_output=True, encoding="utf-8", cwd=str(cwd or self.tmp), env=env,
        )

    def paths(self, *args, **kw):
        r = self.run_script(*args, **kw)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertEqual(len(lines), 2)
        return Path(lines[0]), Path(lines[1])

    def make_repo(self):
        repo = self.tmp / "project" / "repo"
        repo.mkdir(parents=True)
        git = ["git", "-c", "user.name=test", "-c", "user.email=test@example.com"]
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(git + ["commit", "-q", "--allow-empty", "-m", "init"], check=True, cwd=str(repo))
        return repo


class DirOptionTest(OutputPathTestCase):
    def test_dir_option_outside_git(self):
        out = self.tmp / "out"
        md, tasks = self.paths("対応", "--dir", str(out))
        self.assertEqual(md, out / f"{self.today}_工数見積もり_対応.md")
        self.assertEqual(tasks, out / f"{self.today}_工数見積もり_対応.tasks.json")
        self.assertTrue(out.is_dir())

    def test_env_var(self):
        out = self.tmp / "envout"
        md, _ = self.paths("対応", env_dir=out)
        self.assertEqual(md.parent, out)

    def test_dir_option_beats_env_var(self):
        md, _ = self.paths("対応", "--dir", str(self.tmp / "a"), env_dir=self.tmp / "b")
        self.assertEqual(md.parent, self.tmp / "a")

    def test_relative_dir_is_made_absolute(self):
        md, _ = self.paths("対応", "--dir", "rel")
        self.assertEqual(md.parent, self.tmp / "rel")

    def test_dir_is_a_file(self):
        target = self.tmp / "afile"
        target.write_text("x", encoding="utf-8")
        r = self.run_script("対応", "--dir", str(target))
        self.assertEqual(r.returncode, 1)
        self.assertIn("フォルダではありません", r.stderr)

    def test_outside_git_without_dir(self):
        r = self.run_script("対応")
        self.assertEqual(r.returncode, 1)
        self.assertIn("--dir", r.stderr)
        self.assertNotIn("Traceback", r.stderr)


class FileNameTest(OutputPathTestCase):
    def test_label_is_sanitized(self):
        md, _ = self.paths("同じ 対応/内容", "--dir", str(self.tmp))
        self.assertEqual(md.name, f"{self.today}_工数見積もり_同じ-対応-内容.md")

    def test_empty_label(self):
        r = self.run_script("  ", "--dir", str(self.tmp))
        self.assertEqual(r.returncode, 1)
        self.assertIn("使い方", r.stderr)

    def test_number_is_added_when_md_exists(self):
        md, _ = self.paths("対応", "--dir", str(self.tmp))
        md.write_text("x", encoding="utf-8")
        md2, tasks2 = self.paths("対応", "--dir", str(self.tmp))
        self.assertEqual(md2.name, f"{self.today}_工数見積もり_対応_2.md")
        self.assertEqual(tasks2.name, f"{self.today}_工数見積もり_対応_2.tasks.json")

    def test_number_is_added_when_only_tasks_json_exists(self):
        _, tasks = self.paths("対応", "--dir", str(self.tmp))
        tasks.write_text("{}", encoding="utf-8")
        md2, _ = self.paths("対応", "--dir", str(self.tmp))
        self.assertEqual(md2.name, f"{self.today}_工数見積もり_対応_2.md")


@unittest.skipUnless(HAS_GIT, "git が必要")
class DefaultDirTest(OutputPathTestCase):
    def test_default_is_next_to_repo(self):
        repo = self.make_repo()
        md, _ = self.paths("対応", cwd=repo)
        self.assertEqual(md.parent, repo.parent / "docs")

    def test_default_from_subdirectory(self):
        repo = self.make_repo()
        sub = repo / "a" / "b"
        sub.mkdir(parents=True)
        md, _ = self.paths("対応", cwd=sub)
        self.assertEqual(md.parent, repo.parent / "docs")

    def test_default_from_worktree(self):
        # worktree はリポジトリの中に作られることがある。その場合も元のリポジトリの親に保存する
        repo = self.make_repo()
        wt = repo / ".claude" / "worktrees" / "wt"
        subprocess.run(["git", "worktree", "add", "-q", str(wt)], check=True, cwd=str(repo),
                       capture_output=True)
        md, _ = self.paths("対応", cwd=wt)
        self.assertEqual(md.parent, repo.parent / "docs")
        self.assertFalse((repo / ".claude" / "worktrees" / "docs").exists())


if __name__ == "__main__":
    unittest.main()
