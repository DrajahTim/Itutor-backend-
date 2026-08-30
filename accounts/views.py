from django.shortcuts import render

# Create your views here.
from django.contrib.auth import get_user_model
from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView

from .serializers import RegisterSerializer, UserSerializer

User = get_user_model()


class RegisterView(generics.CreateAPIView):
    # Public endpoint — anyone can register.
    queryset = User.objects.all()
    permission_classes = [permissions.AllowAny]
    serializer_class = RegisterSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        # Issue tokens immediately on registration so the frontend
        # doesn't need a separate login call right after signing up.
        refresh = TokenObtainPairSerializer.get_token(user)
        return Response(
            {
                "user": UserSerializer(user).data,
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            },
            status=201,
        )


class EmailTokenObtainPairSerializer(TokenObtainPairSerializer):
    # simplejwt defaults to expecting a "username" field for login.
    # We override this so login works with "email" instead, matching
    # our USERNAME_FIELD setting on the User model.
    username_field = User.USERNAME_FIELD


class LoginView(TokenObtainPairView):
    # Public endpoint — POST email + password, get back access + refresh tokens.
    permission_classes = [permissions.AllowAny]
    serializer_class = EmailTokenObtainPairSerializer


class MeView(generics.RetrieveAPIView):
    # Protected endpoint — requires a valid access token.
    # Returns whichever user the token belongs to (not by ID in the URL,
    # to avoid users being able to view each other's profiles).
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user