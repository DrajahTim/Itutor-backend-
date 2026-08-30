from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

User = get_user_model()


class RegisterSerializer(serializers.ModelSerializer):
    # write_only so the password never gets sent back out in a response.
    # validate_password runs Django's built-in password strength checks
    # (min length, not too common, not all numeric, etc.)
    password = serializers.CharField(write_only=True, validators=[validate_password])

    class Meta:
        model = User
        fields = ["id", "email", "username", "full_name", "password", "role"]
        # role is included so we can see it in responses, but we never
        # want a registering user to set it themselves to "admin" — so
        # we force it in create() below regardless of what's submitted.
        extra_kwargs = {"role": {"read_only": True}}

    def create(self, validated_data):
        # create_user (not create) makes sure the password is hashed
        # properly instead of stored as plain text.
        return User.objects.create_user(
            email=validated_data["email"],
            username=validated_data["username"],
            full_name=validated_data["full_name"],
            password=validated_data["password"],
            role="student",
        )


class UserSerializer(serializers.ModelSerializer):
    # Used for the /me/ endpoint — read-only view of a user's own profile.
    class Meta:
        model = User
        fields = ["id", "email", "username", "full_name", "role", "created_at"]