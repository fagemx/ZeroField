import uuid
import test_execution as execution_fixture
from project_assistant import orchestrator
from project_docs import repository as repo
from project_docs.doc_schema import column_ids


class OrchestrationFixture:
    setUp=execution_fixture.PostgreSQLExecutionTests.setUp
    tearDown=execution_fixture.PostgreSQLExecutionTests.tearDown

    def run_record(self,**kwargs):
        return orchestrator.create_run(self.conn,self.me,self.slug,'Synthetic goal',client_request_id=uuid.uuid4().hex,**kwargs)

    def task_record(self,run=None,**kwargs):
        run=run or self.run_record()
        return orchestrator.create_task(self.conn,self.me,self.slug,run['id'],objective='Synthetic task',
            **({'agent_key':'sheet_ops'} if 'agent_key' not in kwargs and 'label_selector' not in kwargs else {}),**kwargs)

    def sheet_scope(self,rows=None,columns=None):
        tab=repo.get_tab(self.conn,self.slug,'shots')
        return {'target_tab':'shots','table_id':'b_table','base_revision':tab['revision'],
                'row_ids':rows or ['b_shot1','b_shot2'],'column_ids':columns or column_ids(tab['doc']['content'][0])}
