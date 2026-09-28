import sqlalchemy

class Massage:
    def __init__(self, role, content):
        self.role = role
        self.content = content
m1 = Massage("user", "你好")
m2 = Massage("assistant", "你好，有什么我可以帮助你的吗？")

print(m1.role,m1.content)
print(m2.role,m2.content)

print(sqlalchemy.__version__)



