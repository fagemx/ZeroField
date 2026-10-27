import io
import json
import unittest
import urllib.error

from project_assistant import providers, worker


class ProviderTests(unittest.TestCase):
    def test_provider_error_body_is_not_persisted_or_echoed_as_a_secret(self):
        def opener(request,timeout):
            raise urllib.error.HTTPError(request.full_url,401,'Unauthorized',{},io.BytesIO(b'provider echoed private-fixture-secret'))
        result=providers.run_openai_compat_turn(config=providers.ProviderConfig('openai_compat','http://127.0.0.1/v1','private-fixture-secret','fixture'),
            instructions='',turn_text='',call_tool=lambda *_:'',timeout=5,opener=opener)
        self.assertEqual(result.error_kind,'auth')
        self.assertNotIn('private-fixture-secret',result.error)
    def test_default_is_local_open_weights_and_cli_is_explicit(self):
        default = providers.provider_from_env({})
        self.assertEqual((default.kind, default.base_url, default.model), ("openai_compat", "http://127.0.0.1:11434/v1", "qwen3.8:27b"))
        configured = worker.settings_from_env({"OPENBENCH_PROVIDER": "codex_cli", "OPENBENCH_MODEL": "chosen-model"})
        self.assertEqual(configured.engine, "codex")
        self.assertEqual(configured.model, "chosen-model")

    def test_image_inputs_and_tool_roundtrip_use_selected_endpoint(self):
        requests = []
        responses = [
            {"choices": [{"message": {"content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "read_page", "arguments": '{"key":"shots"}'}}]}}]},
            {"choices": [{"message": {"content": "Ready"}}]},
        ]
        def open_request(request, timeout):
            requests.append((request.full_url, json.loads(request.data)))
            return io.BytesIO(json.dumps(responses.pop(0)).encode())
        result = providers.run_openai_compat_turn(
            config=providers.provider_from_env({"OPENBENCH_API_BASE": "http://127.0.0.1:11434/v1", "OPENBENCH_MODEL": "vision"}),
            instructions="Use provided project data", turn_text="Inspect this", images=["data:image/png;base64,cG5n"],
            call_tool=lambda name, args: "row_id=shot1", timeout=10, opener=open_request)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.answer, "Ready")
        self.assertEqual(requests[0][0], "http://127.0.0.1:11434/v1/chat/completions")
        self.assertEqual(requests[0][1]["messages"][1]["content"][1]["image_url"]["url"], "data:image/png;base64,cG5n")
        self.assertEqual(requests[1][1]["messages"][-1], {"role": "tool", "tool_call_id": "c1", "content": "row_id=shot1"})


if __name__ == "__main__":
    unittest.main()
